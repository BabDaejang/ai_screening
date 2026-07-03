"""2단계: LLM 기반 AI 사용 의심 스크리닝.

선택된 LLM 프로바이더를 통해 각 제출물을 분석하고
risk_score, signals, fact_claims 등을 반환한다.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from providers.base import LLMProvider

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 시스템 프롬프트 (한국어)
# ──────────────────────────────────────────────

SCREENING_SYSTEM_PROMPT = """당신은 한국 고등학교 독서 과제 제출물에서 AI(챗봇) 사용 흔적을 탐지하는 전문 분석가입니다.

## 분석 기준

### AI 문체 신호 (위험도 상승 요인)
1. **과도하게 균형 잡힌 결론**: 양면을 기계적으로 나열하고 무난하게 마무리하는 패턴
2. **기계적 병렬 구조**: 동일한 문장 구조가 3회 이상 반복 ("첫째, ~하다. 둘째, ~하다. 셋째, ~하다.")
3. **번역투 한국어**: "~에 있어서", "~함에 틀림없다", "~라고 할 수 있을 것이다" 등 과도한 번역체
4. **상투구 남용**: "단순한 X를 넘어", "시사하는 바가 크다", "다양한 측면에서", "종합적으로 볼 때" 등

### 구체성 결핍 (위험도 상승 요인)
5. **매끄러운 주제 요약**: 책의 줄거리나 주제를 유창하게 요약하지만 구체적인 장면, 페이지, 개인적 경험이 없음
6. **개인 체험 부재**: "이 책을 읽고 느낀 점" 류의 일반적 감상만 있고 구체적 독서 상황이나 계기가 없음

### 진정성 신호 (위험도 감소 요인)
7. **오타/비문**: 맞춤법 오류, 어색한 문장이 있으면 오히려 진정성 지표
8. **독특한 개인 디테일**: 구체적 경험, 독특한 비유, 감정적 솔직함
9. **비정형 구조**: 문단 길이가 들쭉날쭉, 논리 흐름이 완벽하지 않음

### 주의 사항
- 글이 잘 쓰여졌다는 이유만으로 위험 점수를 올리지 마십시오.
- 한국어 실력이 좋은 학생의 자연스러운 글쓰기와 AI 문체를 구별하십시오.
- 확실하지 않으면 낮은 점수를 부여하십시오.

## 응답 형식

반드시 아래 JSON 형식으로만 응답하십시오. 코드 펜스(```)나 추가 설명 없이 순수 JSON만 출력하십시오.

{
    "risk_score": <0-100 정수, 100이 가장 의심>,
    "book_title": "<감지된 책 제목 또는 null>",
    "signals": ["<발견된 AI 사용 신호 목록>"],
    "fact_claims": ["<본문에서 추출한 사실 주장 목록 — 3단계 검증용>"],
    "rationale": "<판단 근거 요약>"
}
"""


# ──────────────────────────────────────────────
# JSON 파싱 유틸리티
# ──────────────────────────────────────────────

def _parse_screening_response(raw: str) -> dict[str, Any] | None:
    """LLM 응답에서 JSON을 파싱한다.

    코드 펜스가 포함된 경우에도 내부 JSON을 추출하여 파싱을 시도한다.
    실패 시 None을 반환한다.
    """
    # 코드 펜스 제거
    cleaned = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    # JSON 블록 추출 시도 (첫 번째 { ~ 마지막 } )
    brace_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if brace_match:
        cleaned = brace_match.group(0)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None

    # 필수 필드 검증
    required = {"risk_score", "signals", "rationale"}
    if not required.issubset(data.keys()):
        return None

    # 타입 보정
    try:
        data["risk_score"] = int(data["risk_score"])
    except (ValueError, TypeError):
        data["risk_score"] = 50  # 파싱 불가 시 중간값

    data.setdefault("book_title", None)
    data.setdefault("fact_claims", [])
    if not isinstance(data["signals"], list):
        data["signals"] = [str(data["signals"])]
    if not isinstance(data["fact_claims"], list):
        data["fact_claims"] = [str(data["fact_claims"])]

    return data


# ──────────────────────────────────────────────
# 메인 함수
# ──────────────────────────────────────────────

def run_stage2(
    submissions: list[dict],
    provider: LLMProvider,
    config: dict,
) -> list[dict]:
    """2단계 LLM 스크리닝을 실행한다.

    Args:
        submissions: 1단계를 통과한 제출물 리스트.
            각 항목은 최소 {"filename": str, "text": str} 포함.
        provider: LLMProvider 구현체 인스턴스.
        config: 설정 dict (현재 단계에서는 직접 사용하지 않으나 확장성 위해 전달).

    Returns:
        submissions 리스트 (각 항목에 stage2 결과가 추가됨).
    """
    total = len(submissions)

    for idx, sub in enumerate(submissions, 1):
        filename = sub.get("filename", f"submission_{idx}")
        text = sub.get("text", "")

        logger.info("[2단계] (%d/%d) %s 스크리닝 중…", idx, total, filename)

        if not text.strip():
            sub["ai_score"] = 0
            sub["stage2"] = {
                "risk_score": 0,
                "book_title": None,
                "signals": [],
                "fact_claims": [],
                "rationale": "빈 텍스트",
            }
            continue

        # 첫 번째 시도
        parsed = _call_and_parse(provider, text)

        # 파싱 실패 시 1회 재시도
        if parsed is None:
            logger.warning("[2단계] %s — JSON 파싱 실패, 재시도…", filename)
            parsed = _call_and_parse(provider, text)

        if parsed is None:
            logger.error("[2단계] %s — 재시도 후에도 파싱 실패 또는 API 에러", filename)
            sub["ai_score"] = 0
            sub["stage2"] = {
                "risk_score": 0,
                "book_title": None,
                "signals": [],
                "fact_claims": [],
                "rationale": "LLM 응답 파싱 실패 또는 API 호출 오류",
                "error": True,
                "error_message": "2단계 AI 스크리닝 중 API 에러 혹은 JSON 파싱 실패가 발생했습니다."
            }
            continue

        sub["ai_score"] = parsed["risk_score"]
        sub["stage2"] = parsed

    return submissions


def _call_and_parse(provider: LLMProvider, text: str) -> dict[str, Any] | None:
    """프로바이더 호출 후 JSON 파싱까지 수행.

    API 에러 발생 시 None 반환 (크래시 방지).
    """
    try:
        raw_response = provider.screen(SCREENING_SYSTEM_PROMPT, text)
    except Exception as exc:
        logger.error("[2단계] API 호출 에러: %s", exc)
        return None

    # provider.screen이 이미 dict를 반환하는 경우 처리
    if isinstance(raw_response, dict):
        # 필수 필드 존재 여부 확인
        if "risk_score" in raw_response:
            raw_response.setdefault("book_title", None)
            raw_response.setdefault("fact_claims", [])
            raw_response.setdefault("signals", [])
            raw_response.setdefault("rationale", "")
            return raw_response

    # 문자열 응답인 경우 파싱
    if isinstance(raw_response, str):
        return _parse_screening_response(raw_response)

    return None
