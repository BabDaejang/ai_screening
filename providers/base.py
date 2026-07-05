"""LLM 프로바이더 추상 인터페이스."""

from abc import ABC, abstractmethod
from typing import Optional


class LLMProvider(ABC):
    """모든 LLM 프로바이더가 구현해야 하는 인터페이스."""

    @classmethod
    @abstractmethod
    def list_available_models(cls, api_key: str) -> list[str]:
        """해당 프로바이더가 지원하는 텍스트 생성/대화 모델 목록을 API를 통해 조회합니다.

        Args:
            api_key: API 키

        Returns:
            모델 식별자(ID) 리스트
        """
        pass

    def __init__(self, api_key: str, model_screening: str, model_verify: str, cost_tracker: Optional[object] = None):
        self.api_key = api_key
        self.model_screening = model_screening
        self.model_verify = model_verify
        self.cost_tracker = cost_tracker
        # 토큰 사용량 누적
        self._usage = {
            "screening": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0},
            "verify": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0},
            "factsheet": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0},
        }
        self._web_search_count = 0

    @abstractmethod
    def screen(self, system_prompt: str, text: str, max_tokens: int = 1500) -> dict:
        """2단계: 제출물 AI 스크리닝.

        Returns:
            {
                "risk_score": int (0-100),
                "book_title": str or None,
                "signals": list[str],
                "fact_claims": list[str],
                "rationale": str
            }
        """
        pass

    @abstractmethod
    def generate_factsheet(self, book_title: str, prompt_override: Optional[str] = None) -> str:
        """3-1단계: 책 제목에 대한 사실 정보(팩트시트) 생성.

        Returns:
            마크다운 포맷의 팩트시트 내용
        """
        pass

    def generate_enriched_factsheet(self, book_title: str, prompt_override: Optional[str] = None) -> str:
        """3-1단계 심층보강: 책 제목에 대한 풍부한 사실 정보(팩트시트) 생성."""
        return self.generate_factsheet(book_title, prompt_override=prompt_override)

    @abstractmethod
    def verify_claims(self, system_prompt: str, claims: list, full_text: str, max_tokens: int = 2000) -> dict:
        """3-2단계: 팩트시트 기반 사실 검증.

        Returns:
            {
                "claims": [
                    {
                        "claim": str,
                        "verdict": "일치" | "모순" | "판단불가",
                        "explanation": str,
                        "factsheet_basis": str or None
                    }
                ],
                "hallucination_score": int (0-100),
                "overall": str,
                "interview_questions": list[str]  # 면담 확인 질문 3개
            }
        """
        pass

    def get_usage(self) -> dict:
        """누적 토큰 사용량 반환."""
        return {
            "usage": self._usage,
            "web_search_count": self._web_search_count,
            "model_screening": self.model_screening,
            "model_verify": self.model_verify,
        }

    def _update_usage(self, stage: str, input_tokens: int = 0, output_tokens: int = 0,
                      cache_read_tokens: int = 0, cache_write_tokens: int = 0):
        """토큰 사용량 업데이트."""
        self._usage[stage]["input_tokens"] += input_tokens
        self._usage[stage]["output_tokens"] += output_tokens
        self._usage[stage]["cache_read_tokens"] += cache_read_tokens
        self._usage[stage]["cache_write_tokens"] += cache_write_tokens

        # 비용 추적기에 즉시 연동
        if self.cost_tracker:
            model_name = self.model_verify if stage in ("verify", "factsheet") else self.model_screening
            if model_name:
                self.cost_tracker.add_usage(
                    model=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_write_tokens=cache_write_tokens
                )

    def _add_web_search(self, count: int = 1):
        """웹 검색 횟수를 기록합니다."""
        self._web_search_count += count
        if self.cost_tracker:
            self.cost_tracker.add_web_search(count)

    @property
    def provider_name(self) -> str:
        """프로바이더 이름 (하위 클래스에서 정의)."""
        return self.__class__.__name__.replace("Provider", "").lower()
