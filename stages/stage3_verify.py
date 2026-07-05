"""3단계: 팩트시트 기반 사실 검증.

2단계에서 추출된 fact_claims를 책별 팩트시트와 대조하여
일치/모순/판단불가를 판정하고, 면담 질문을 생성한다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from collections import defaultdict
from typing import Any

from providers.base import LLMProvider

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 팩트시트 관리
# ──────────────────────────────────────────────

def _normalize_title(title: str) -> str:
    """책 제목을 파일명으로 사용할 수 있도록 정규화한다.

    공백, 특수문자 제거 → 소문자 변환.
    """
    # 유니코드 정규화
    normalized = unicodedata.normalize("NFC", title)
    # 공백·특수문자 제거 (한글, 영숫자만 유지)
    normalized = re.sub(r"[^\w가-힣a-zA-Z0-9]", "", normalized)
    return normalized.lower()


def ensure_factsheet(
    book_title: str,
    provider: LLMProvider,
    factsheets_dir: str,
    no_web: bool,
) -> str | None:
    """팩트시트를 확보한다 (캐시 우선).

    Args:
        book_title: 책 제목.
        provider: LLM 프로바이더 인스턴스.
        factsheets_dir: 팩트시트 저장 디렉토리 경로.
        no_web: True이면 웹 검색 없이 캐시만 사용.

    Returns:
        팩트시트 내용 문자열 또는 None.
    """
    if not book_title:
        return None

    normalized = _normalize_title(book_title)
    if not normalized:
        return None

    os.makedirs(factsheets_dir, exist_ok=True)
    filepath = os.path.join(factsheets_dir, f"{normalized}.md")

    # 캐시 확인
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if content.strip():
                logger.info("[3단계] 팩트시트 캐시 사용: %s", filepath)
                return content
        except OSError as exc:
            logger.warning("[3단계] 팩트시트 읽기 실패: %s — %s", filepath, exc)

    # 웹 검색 비활성화 시
    if no_web:
        logger.info("[3단계] no_web=True — 팩트시트 생성 건너뜀: %s", book_title)
        return None

    # 프로바이더를 통해 팩트시트 생성
    try:
        logger.info("[3단계] 팩트시트 생성 중: %s", book_title)
        content = provider.generate_factsheet(book_title)
    except Exception as exc:
        logger.error("[3단계] 팩트시트 생성 실패: %s — %s", book_title, exc)
        return None

    if not content or not content.strip():
        logger.warning("[3단계] 빈 팩트시트 반환됨: %s", book_title)
        return None

    # 캐시에 저장
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("[3단계] 팩트시트 저장 완료: %s", filepath)
    except OSError as exc:
        logger.warning("[3단계] 팩트시트 저장 실패: %s — %s", filepath, exc)

    return content


# ──────────────────────────────────────────────
# 검증 시스템 프롬프트
# ──────────────────────────────────────────────

def _build_verify_system_prompt(factsheet: str) -> str:
    """검증용 시스템 프롬프트를 생성한다."""
    return f"""당신은 독서 감상문의 사실 주장을 검증하는 전문가입니다.

## 팩트시트

아래는 해당 도서에 대한 팩트시트입니다. 이 팩트시트만을 근거로 판단하십시오.

---
{factsheet}
---

## 검증 지침

1. 학생이 주장한 각 사실(fact_claim)을 위 팩트시트와 대조하십시오.
2. 판정 기준:
   - **일치**: 주장이 팩트시트의 내용과 부합하는 경우
   - **모순**: 주장이 팩트시트의 내용과 명백히 모순되는 경우 (구체적으로 어떻게 모순되는지 설명)
   - **판단불가**: 주장이 팩트시트에 포함되지 않아 확인할 수 없는 경우

3. **중요**: 팩트시트에 없는 내용은 반드시 '판단불가'로 판정하십시오.
   절대로 당신의 사전 지식으로 '모순'을 판단하지 마십시오.

4. '모순' 및 '판단불가' 판정이 있는 주장을 바탕으로, 학생에게 물어볼 면담 확인 질문 3개를 생성하십시오.

## 응답 형식

반드시 아래 JSON 형식으로만 응답하십시오. 코드 펜스(```)나 추가 설명 없이 순수 JSON만 출력하십시오.

{{
    "claims": [
        {{
            "claim": "<원래 사실 주장>",
            "verdict": "일치" | "모순" | "판단불가",
            "explanation": "<판정 근거 설명>",
            "factsheet_basis": "<팩트시트에서 관련 내용 인용 또는 null>"
        }}
    ],
    "hallucination_score": <0-100 정수, 모순이 많을수록 높음>,
    "overall": "<종합 판정 요약>",
    "interview_questions": ["<면담 질문 1>", "<면담 질문 2>", "<면담 질문 3>"]
}}
"""


# ──────────────────────────────────────────────
# JSON 파싱 유틸리티
# ──────────────────────────────────────────────

def _parse_verify_response(raw: str) -> dict[str, Any] | None:
    """검증 LLM 응답에서 JSON을 파싱한다.

    코드 펜스, 추가 텍스트 등을 제거하고 파싱을 시도한다.
    """
    cleaned = raw.strip()

    # 코드 펜스 제거
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    # JSON 블록 추출
    brace_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if brace_match:
        cleaned = brace_match.group(0)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None

    # 필수 필드 검증
    if "claims" not in data:
        return None

    # 기본값 보정
    data.setdefault("hallucination_score", 0)
    data.setdefault("overall", "")
    data.setdefault("interview_questions", [])

    try:
        data["hallucination_score"] = int(data["hallucination_score"])
    except (ValueError, TypeError):
        data["hallucination_score"] = 50

    if not isinstance(data["claims"], list):
        data["claims"] = []

    if not isinstance(data["interview_questions"], list):
        data["interview_questions"] = [str(data["interview_questions"])]

    return data


# ──────────────────────────────────────────────
# 비용 추정
# ──────────────────────────────────────────────

def estimate_cost(
    candidates: list[dict],
    config: dict,
) -> tuple[int, float]:
    """3단계 실행 전 예상 비용을 추정하고 출력한다.

    Args:
        candidates: 3단계 대상 후보 리스트.
        config: 설정 dict (pricing 정보 포함).

    Returns:
        (대상 건수, 예상 비용 USD).
    """
    count = len(candidates)

    # 고유 책 제목 수 (팩트시트 생성 비용)
    unique_books = set()
    for c in candidates:
        title = c.get("stage2", {}).get("book_title") or c.get("book_title")
        if title:
            unique_books.add(title)
    num_books = len(unique_books)

    # 평균 토큰 추정 (한국어 기준: 글자당 약 1.5 토큰)
    avg_input_tokens_per_verify = 3000   # 팩트시트 + 시스템 프롬프트 + 주장 목록
    avg_output_tokens_per_verify = 1000  # 검증 결과
    avg_input_tokens_per_factsheet = 500  # 팩트시트 생성 요청
    avg_output_tokens_per_factsheet = 1500  # 팩트시트 내용

    # 기본 단가 (config에서 읽기 시도, 실패 시 기본값 사용)
    pricing = config.get("pricing", {})

    # 모든 프로바이더의 최대 단가를 보수적으로 사용
    max_input_price = 0.0
    max_output_price = 0.0
    for provider_prices in pricing.values():
        if isinstance(provider_prices, dict) and "per_1000_calls" not in provider_prices:
            for model_prices in provider_prices.values():
                if isinstance(model_prices, dict):
                    max_input_price = max(max_input_price, model_prices.get("input", 0))
                    max_output_price = max(max_output_price, model_prices.get("output", 0))

    # fallback
    if max_input_price == 0:
        max_input_price = 3.0
    if max_output_price == 0:
        max_output_price = 15.0

    # 비용 계산 (USD per 1M tokens)
    factsheet_cost = num_books * (
        (avg_input_tokens_per_factsheet * max_input_price / 1_000_000)
        + (avg_output_tokens_per_factsheet * max_output_price / 1_000_000)
    )
    verify_cost = count * (
        (avg_input_tokens_per_verify * max_input_price / 1_000_000)
        + (avg_output_tokens_per_verify * max_output_price / 1_000_000)
    )
    total_cost = factsheet_cost + verify_cost

    # 웹 검색 비용
    web_cost_per_1000 = pricing.get("web_search", {}).get("per_1000_calls", 10.0)
    web_cost = num_books * (web_cost_per_1000 / 1000)
    total_cost += web_cost

    print(f"\n{'='*50}")
    print(f"  3단계 비용 추정")
    print(f"{'='*50}")
    print(f"  대상 학생 수   : {count}명")
    print(f"  고유 도서 수   : {num_books}권")
    print(f"  팩트시트 비용  : ${factsheet_cost:.4f}")
    print(f"  검증 비용      : ${verify_cost:.4f}")
    print(f"  웹 검색 비용   : ${web_cost:.4f}")
    print(f"  예상 총 비용   : ${total_cost:.4f}")
    print(f"{'='*50}\n")

    return count, round(total_cost, 4)


# ──────────────────────────────────────────────
# 메인 함수
# ──────────────────────────────────────────────

def run_stage3(
    candidates: list[dict],
    provider: LLMProvider,
    factsheets_dir: str,
    config: dict,
    no_web: bool,
    check_cb = None,
) -> list[dict]:
    """3단계 사실 검증을 실행한다."""
    # 책 제목별로 그룹핑 (캐시 효율성)
    book_groups: dict[str, list[int]] = defaultdict(list)
    for idx, cand in enumerate(candidates):
        title = (
            cand.get("stage2", {}).get("book_title")
            or cand.get("book_title")
            or "unknown"
        )
        book_groups[title].append(idx)

    total = len(candidates)
    processed = 0
    consecutive_errors = 0
    last_error_msg = ""

    for book_title, indices in book_groups.items():
        # 팩트시트 확보
        try:
            factsheet = ensure_factsheet(book_title, provider, factsheets_dir, no_web)
        except Exception as exc:
            factsheet = None
            logger.error("[3단계] 팩트시트 확보 중 예외 발생: %s", exc)

        for idx in indices:
            cand = candidates[idx]
            processed += 1
            filename = cand.get("filename", f"candidate_{idx}")

            if check_cb:
                check_cb("3단계", processed, total, filename)

            logger.info(
                "[3단계] (%d/%d) %s 검증 중… (도서: %s)",
                processed, total, filename, book_title,
            )

            fact_claims = (
                cand.get("stage2", {}).get("fact_claims")
                or cand.get("fact_claims")
                or []
            )
            full_text = cand.get("text", "")

            # 팩트시트 없으면 검증 불가
            if factsheet is None:
                cand["stage3"] = {
                    "claims": [],
                    "hallucination_score": 0,
                    "overall": "팩트시트 없음 — 검증 불가",
                    "interview_questions": [],
                    "factsheet_available": False,
                }
                continue

            # fact_claims가 비어있으면 건너뜀
            if not fact_claims:
                cand["stage3"] = {
                    "claims": [],
                    "hallucination_score": 0,
                    "overall": "사실 주장 없음 — 검증 건너뜀",
                    "interview_questions": [],
                    "factsheet_available": True,
                }
                continue

            # 검증 수행
            parsed, err_msg, is_json_err = _verify_and_parse_with_error(
                provider, factsheet, fact_claims, full_text,
            )

            # 파싱 실패 시 1회 재시도 (총 2회 제한)
            if parsed is None and is_json_err:
                logger.warning("[3단계] %s — JSON 파싱 실패, 재시도 (2번째)…", filename)
                parsed, err_msg, is_json_err = _verify_and_parse_with_error(
                    provider, factsheet, fact_claims, full_text,
                )

            if parsed is None:
                if is_json_err:
                    logger.error("[3단계] %s — 2회 연속 JSON 파싱 실패로 해당 항목 스킵: %s", filename, err_msg)
                else:
                    consecutive_errors += 1
                    logger.error("[3단계] %s — API 호출 에러 (%d/3): %s", filename, consecutive_errors, err_msg)
                    if consecutive_errors >= 3:
                        raise Exception(f"연속 3회 API 에러 발생으로 중단됨. 최근 에러: {err_msg}")
                
                cand["stage3"] = {
                    "claims": [],
                    "hallucination_score": 0,
                    "overall": f"JSON 파싱 실패 또는 API 호출 오류: {err_msg}",
                    "interview_questions": [],
                    "factsheet_available": True,
                    "error": True,
                    "error_message": err_msg
                }
                continue

            consecutive_errors = 0
            parsed["factsheet_available"] = True
            cand["stage3"] = parsed

            # 모순 판정이 있으면 등급을 '최우선'으로 격상
            has_contradiction = any(
                claim.get("verdict") == "모순"
                for claim in parsed.get("claims", [])
            )
            if has_contradiction:
                cand["tier"] = "최우선"
                logger.info("[3단계] %s — 모순 발견, 등급 '최우선' 격상", filename)

    return candidates


def _verify_and_parse_with_error(
    provider: LLMProvider,
    factsheet: str,
    fact_claims: list[str],
    full_text: str,
) -> tuple[dict[str, Any] | None, str, bool]:
    """프로바이더를 통해 검증 수행 후 JSON 파싱 및 에러 메시지와 json_decode_error 여부 반환."""
    system_prompt = _build_verify_system_prompt(factsheet)

    try:
        raw_response = provider.verify_claims(
            system_prompt, fact_claims, full_text,
        )
    except Exception as exc:
        err_msg = str(exc)
        logger.error("[3단계] API 호출 에러: %s", err_msg)
        return None, f"API 호출 에러: {err_msg}", False

    if isinstance(raw_response, dict):
        if "error" in raw_response and "JSON 파싱" in raw_response.get("error", ""):
            return None, raw_response["error"], True
        if "claims" in raw_response:
            raw_response.setdefault("hallucination_score", 0)
            raw_response.setdefault("overall", "")
            raw_response.setdefault("interview_questions", [])
            return raw_response, "", False

    if isinstance(raw_response, str):
        parsed = _parse_verify_response(raw_response)
        if parsed is not None:
            return parsed, "", False
        return None, f"JSON 파싱 실패 (응답 일부: {raw_response[:100]})", True

    return None, "알 수 없는 응답 형식", False
