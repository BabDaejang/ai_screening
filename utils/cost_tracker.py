"""API 비용 추적 모듈.

모델별 토큰 사용량과 웹 검색 호출 수를 추적하고,
config.yaml의 단가 정보를 기반으로 예상 비용을 산출합니다.
"""

import logging
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# 프로젝트 루트의 config.yaml 기본 경로
_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


class CostTracker:
    """API 토큰 사용량 및 비용 추적기."""

    def __init__(self, config: dict = None):
        """CostTracker 초기화.

        Args:
            config: config.yaml에서 로드된 설정 딕셔너리. None이면 파일에서 로드 시도.
        """
        self._usage: dict[str, dict[str, int]] = {}
        self._web_search_count: int = 0
        self._pricing: dict = {}
        self._web_search_pricing: float = 0.0

        self._load_pricing(config)

    def _load_pricing(self, config: dict = None) -> None:
        """단가 정보를 로드합니다."""
        if config is None:
            path = _DEFAULT_CONFIG_PATH
            try:
                with open(path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
            except FileNotFoundError:
                logger.warning("설정 파일 없음: %s — 비용 계산 불가", path)
                return
            except yaml.YAMLError as e:
                logger.error("설정 파일 파싱 오류: %s", e)
                return

        pricing = config.get("pricing", {})

        # 프로바이더별 모델 단가를 평탄화하여 {model_name: {...}} 형태로 저장
        for provider, models in pricing.items():
            if provider == "web_search":
                self._web_search_pricing = models.get("per_1000_calls", 0.0)
                continue
            if not isinstance(models, dict):
                continue
            for model_name, price_info in models.items():
                if isinstance(price_info, dict):
                    self._pricing[model_name] = price_info

    def add_usage(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> None:
        """토큰 사용량을 추가합니다.

        Args:
            model: 모델 이름 (예: 'claude-haiku-4-5').
            input_tokens: 입력 토큰 수.
            output_tokens: 출력 토큰 수.
            cache_read_tokens: 캐시 읽기 토큰 수.
            cache_write_tokens: 캐시 쓰기 토큰 수.
        """
        if model not in self._usage:
            self._usage[model] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
            }
        self._usage[model]["input_tokens"] += input_tokens
        self._usage[model]["output_tokens"] += output_tokens
        self._usage[model]["cache_read_tokens"] += cache_read_tokens
        self._usage[model]["cache_write_tokens"] += cache_write_tokens

    def add_web_search(self, count: int = 1) -> None:
        """웹 검색 호출 횟수를 추가합니다."""
        self._web_search_count += count

    def _calculate_model_cost(self, model: str, usage: dict[str, int]) -> float:
        """단일 모델의 예상 비용을 계산합니다 (USD)."""
        price = self._pricing.get(model)
        if not price:
            logger.debug("모델 '%s'의 단가 정보 없음 — 비용 0으로 처리", model)
            return 0.0

        input_price = price.get("input", 0.0)   # USD per 1M tokens
        output_price = price.get("output", 0.0)
        cache_read_ratio = price.get("cache_read_ratio", 0.1)
        cache_write_ratio = price.get("cache_write_ratio", 1.25)

        cost = 0.0
        cost += (usage["input_tokens"] / 1_000_000) * input_price
        cost += (usage["output_tokens"] / 1_000_000) * output_price
        cost += (usage["cache_read_tokens"] / 1_000_000) * (input_price * cache_read_ratio)
        cost += (usage["cache_write_tokens"] / 1_000_000) * (input_price * cache_write_ratio)

        return cost

    def get_summary(self) -> dict:
        """전체 비용 요약을 반환합니다.

        Returns:
            {
                "models": {
                    "model_name": {
                        "input_tokens": int,
                        "output_tokens": int,
                        "cache_read_tokens": int,
                        "cache_write_tokens": int,
                        "estimated_cost_usd": float
                    }, ...
                },
                "web_search": {
                    "count": int,
                    "estimated_cost_usd": float
                },
                "total_estimated_cost_usd": float
            }
        """
        summary: dict = {"models": {}, "web_search": {}, "total_estimated_cost_usd": 0.0}
        total_cost = 0.0

        for model, usage in self._usage.items():
            model_cost = self._calculate_model_cost(model, usage)
            summary["models"][model] = {
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "cache_read_tokens": usage["cache_read_tokens"],
                "cache_write_tokens": usage["cache_write_tokens"],
                "estimated_cost_usd": round(model_cost, 6),
            }
            total_cost += model_cost

        # 웹 검색 비용
        web_cost = (self._web_search_count / 1000) * self._web_search_pricing
        summary["web_search"] = {
            "count": self._web_search_count,
            "estimated_cost_usd": round(web_cost, 6),
        }
        total_cost += web_cost

        summary["total_estimated_cost_usd"] = round(total_cost, 6)
        return summary

    def print_summary(self) -> None:
        """비용 요약을 콘솔에 출력합니다."""
        summary = self.get_summary()

        print("\n" + "=" * 65)
        print("  💰 API 비용 요약")
        print("=" * 65)

        if summary["models"]:
            print(f"\n  {'모델':<25} {'입력':>10} {'출력':>10} {'비용(USD)':>12}")
            print("  " + "-" * 60)

            for model, info in summary["models"].items():
                total_input = info["input_tokens"] + info["cache_read_tokens"] + info["cache_write_tokens"]
                print(
                    f"  {model:<25} {total_input:>10,} {info['output_tokens']:>10,} "
                    f"${info['estimated_cost_usd']:>10.4f}"
                )
                # 캐시 상세 정보 (캐시 사용 시에만 표시)
                if info["cache_read_tokens"] or info["cache_write_tokens"]:
                    print(
                        f"    └─ 캐시 읽기: {info['cache_read_tokens']:,}  "
                        f"캐시 쓰기: {info['cache_write_tokens']:,}"
                    )

        if summary["web_search"]["count"] > 0:
            print(f"\n  🔍 웹 검색: {summary['web_search']['count']}회  "
                  f"${summary['web_search']['estimated_cost_usd']:.4f}")

        print("\n  " + "-" * 60)
        print(f"  합계: ${summary['total_estimated_cost_usd']:.4f}")
        print("=" * 65 + "\n")
