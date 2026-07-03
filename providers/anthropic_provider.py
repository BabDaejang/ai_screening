"""Anthropic(Claude) LLM 프로바이더 구현."""

import json
import logging
import time
from typing import Optional

import anthropic

from providers.base import LLMProvider

logger = logging.getLogger(__name__)

# 팩트시트 생성용 시스템 프롬프트
_FACTSHEET_SYSTEM_PROMPT = """당신은 도서 사실 검증 전문가입니다. 웹 검색을 활용하여 주어진 도서에 대한 팩트시트를 작성하세요.

팩트시트에 반드시 포함할 항목:
1. **저자/출판사 정보**: 저자 이력, 출판 연도, 출판사
2. **주요 등장인물**: 이름, 역할, 관계
3. **챕터 구조**: 각 장의 제목과 핵심 내용 요약
4. **핵심 사건 순서**: 시간순으로 정리된 주요 플롯 포인트
5. **자주 인용되는 구절**: 유명 인용문이나 핵심 문장
6. **자주 혼동되는 항목**: 비슷한 이름의 인물, 헷갈리는 사건 등

중요 규칙:
- 확인할 수 없는 정보는 반드시 '미확인'으로 표기하세요.
- 추측으로 정보를 채우지 마세요.
- 마크다운 형식으로 작성하세요."""

# 검증 지침
_VERIFICATION_INSTRUCTION = """당신은 도서 독후감/독서 제출물의 사실 검증 전문가입니다.

## 팩트시트 (검증 기준)
{factsheet}

## 검증 규칙
1. 각 claim을 위 팩트시트의 내용과 대조하세요.
2. 팩트시트에 해당 내용이 있으면 '일치' 또는 '모순'으로 판정하세요.
3. **팩트시트에 해당 내용이 없으면, verdict는 반드시 '판단불가'로 하세요.**
4. **절대로 모델 자체의 지식으로 '모순'을 판정하지 마세요.** 오직 팩트시트 기준으로만 판단합니다.
5. 각 판정에 대해 팩트시트의 어느 부분을 근거로 했는지 명시하세요.

## 응답 형식 (JSON)
{{
    "claims": [
        {{
            "claim": "검증 대상 주장",
            "verdict": "일치" | "모순" | "판단불가",
            "explanation": "판정 근거 설명",
            "factsheet_basis": "팩트시트에서 참조한 부분 (없으면 null)"
        }}
    ],
    "hallucination_score": 0-100,
    "overall": "전체 평가 요약",
    "interview_questions": ["면담 확인 질문1", "면담 확인 질문2", "면담 확인 질문3"]
}}"""


def _parse_json_safe(text: str) -> Optional[dict]:
    """JSON 파싱을 안전하게 시도. 코드 블록 마커도 처리."""
    if not text:
        return None
    # ```json ... ``` 블록 제거
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # 첫 줄 제거
        lines = cleaned.split("\n", 1)
        if len(lines) > 1:
            cleaned = lines[1]
        # 마지막 ``` 제거
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API를 사용하는 프로바이더."""

    def __init__(self, api_key: str, model_screening: str, model_verify: str, cost_tracker: Optional[object] = None):
        super().__init__(api_key, model_screening, model_verify, cost_tracker)
        self.client = anthropic.Anthropic(api_key=api_key)

    def _call_with_backoff(self, api_call, max_retries: int = 3, base_delay: float = 2.0):
        """429 에러 시 지수 백오프로 재시도."""
        for attempt in range(max_retries + 1):
            try:
                return api_call()
            except anthropic.RateLimitError as e:
                if attempt == max_retries:
                    raise
                delay = base_delay * (2 ** attempt)
                logger.warning(f"429 Rate limit 발생, {delay}초 후 재시도 ({attempt + 1}/{max_retries})")
                time.sleep(delay)
            except anthropic.APIError:
                raise  # 429 외의 API 에러는 바로 전파

    def screen(self, system_prompt: str, text: str, max_tokens: int = 1500) -> dict:
        """2단계: 제출물 AI 스크리닝.

        시스템 프롬프트에 cache_control을 적용하고, JSON 파싱 실패 시 1회 재시도.
        """
        try:
            def _api_call():
                return self.client.messages.create(
                    model=self.model_screening,
                    max_tokens=max_tokens,
                    system=[
                        {
                            "type": "text",
                            "text": system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[{"role": "user", "content": text}],
                )

            response = self._call_with_backoff(_api_call)

            # 토큰 사용량 추적
            usage = response.usage
            self._update_usage(
                "screening",
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            )

            # JSON 파싱 (실패 시 1회 재시도)
            raw_text = response.content[0].text
            result = _parse_json_safe(raw_text)
            if result is not None:
                return result

            # 재시도: JSON으로 다시 요청
            logger.warning("JSON 파싱 실패, 재시도 중...")
            retry_response = self._call_with_backoff(lambda: self.client.messages.create(
                model=self.model_screening,
                max_tokens=max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt + "\n\n반드시 유효한 JSON만 출력하세요. 다른 텍스트는 포함하지 마세요.",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": text}],
            ))

            # 재시도 토큰 사용량 추적
            retry_usage = retry_response.usage
            self._update_usage(
                "screening",
                input_tokens=retry_usage.input_tokens,
                output_tokens=retry_usage.output_tokens,
                cache_read_tokens=getattr(retry_usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(retry_usage, "cache_creation_input_tokens", 0) or 0,
            )

            retry_text = retry_response.content[0].text
            retry_result = _parse_json_safe(retry_text)
            if retry_result is not None:
                return retry_result

            # 재시도도 실패 시 에러 반환
            logger.error(f"JSON 파싱 재시도 실패. 원본 응답: {retry_text[:200]}")
            return {"error": "JSON 파싱 실패", "raw_response": retry_text[:500]}

        except anthropic.RateLimitError as e:
            logger.error(f"Rate limit 초과 (백오프 후에도 실패): {e}")
            return {"error": f"Rate limit 초과: {str(e)}"}
        except anthropic.APIError as e:
            logger.error(f"Anthropic API 에러: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"스크리닝 중 예상치 못한 에러: {e}")
            return {"error": str(e)}

    def generate_factsheet(self, book_title: str, max_tokens: int = 2000) -> str:
        """3-1단계: 웹 검색 기반 팩트시트 생성.

        Claude의 web_search 도구를 활용하여 도서 정보를 수집하고 팩트시트를 생성.
        """
        try:
            user_prompt = f"다음 도서에 대한 팩트시트를 작성해주세요: 《{book_title}》"

            def _api_call():
                return self.client.messages.create(
                    model=self.model_verify,
                    max_tokens=max_tokens,
                    system=_FACTSHEET_SYSTEM_PROMPT,
                    tools=[
                        {
                            "type": "web_search_20250305",
                            "name": "web_search",
                            "max_uses": 5,
                        }
                    ],
                    messages=[{"role": "user", "content": user_prompt}],
                )

            response = self._call_with_backoff(_api_call)

            # 토큰 사용량 추적
            usage = response.usage
            self._update_usage(
                "factsheet",
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            )

            # 웹 검색 사용 횟수 증가
            self._add_web_search(1)

            # 텍스트 콘텐츠 추출 (여러 블록 중 텍스트만)
            text_parts = []
            for block in response.content:
                if hasattr(block, "text"):
                    text_parts.append(block.text)
            factsheet = "\n\n".join(text_parts)

            if not factsheet.strip():
                logger.warning("팩트시트 생성 결과가 비어있음")
                return f"# {book_title} 팩트시트\n\n팩트시트 생성에 실패했습니다."

            return factsheet

        except anthropic.RateLimitError as e:
            logger.error(f"팩트시트 생성 중 Rate limit 초과: {e}")
            return f"# {book_title} 팩트시트\n\n에러: Rate limit 초과 - {str(e)}"
        except anthropic.APIError as e:
            logger.error(f"팩트시트 생성 중 API 에러: {e}")
            return f"# {book_title} 팩트시트\n\n에러: {str(e)}"
        except Exception as e:
            logger.error(f"팩트시트 생성 중 예상치 못한 에러: {e}")
            return f"# {book_title} 팩트시트\n\n에러: {str(e)}"

    def verify_claims(self, system_prompt: str, claims: list, full_text: str, max_tokens: int = 2000) -> dict:
        """3-2단계: 팩트시트 기반 사실 검증.

        시스템 프롬프트(팩트시트 포함)와 사용자 메시지(claims + 원문)를 기반으로 검증.
        """
        try:
            # 사용자 메시지 구성: claims 목록 + 제출물 전문
            claims_text = "\n".join(f"- {claim}" for claim in claims)
            user_message = (
                f"## 검증 대상 주장 목록\n{claims_text}\n\n"
                f"## 제출물 전문\n{full_text}"
            )

            def _api_call():
                return self.client.messages.create(
                    model=self.model_verify,
                    max_tokens=max_tokens,
                    system=[
                        {
                            "type": "text",
                            "text": system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[{"role": "user", "content": user_message}],
                )

            response = self._call_with_backoff(_api_call)

            # 토큰 사용량 추적
            usage = response.usage
            self._update_usage(
                "verify",
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            )

            # JSON 파싱
            raw_text = response.content[0].text
            result = _parse_json_safe(raw_text)
            if result is not None:
                return result

            # 파싱 실패 시 기본 구조 반환
            logger.error(f"검증 결과 JSON 파싱 실패. 원본: {raw_text[:200]}")
            return {
                "error": "JSON 파싱 실패",
                "raw_response": raw_text[:500],
                "claims": [],
                "hallucination_score": -1,
                "overall": "검증 결과 파싱 실패",
                "interview_questions": [],
            }

        except anthropic.RateLimitError as e:
            logger.error(f"검증 중 Rate limit 초과: {e}")
            return {"error": f"Rate limit 초과: {str(e)}"}
        except anthropic.APIError as e:
            logger.error(f"검증 중 API 에러: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"검증 중 예상치 못한 에러: {e}")
            return {"error": str(e)}

    @classmethod
    def list_available_models(cls, api_key: str) -> list[str]:
        """Anthropic API를 사용하여 사용 가능한 Claude 모델 목록을 조회합니다."""
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            try:
                # SDK에서 지원하는 경우
                models = client.models.list()
                return sorted([m.id for m in models])
            except AttributeError:
                # SDK에서 지원하지 않는 경우 REST API 호출
                import requests
                headers = {
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01"
                }
                res = requests.get("https://api.anthropic.com/v1/models", headers=headers, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    return sorted([m["id"] for m in data.get("data", [])])
                else:
                    logger.error(f"Anthropic 모델 조회 실패: HTTP {res.status_code} - {res.text}")
                    raise Exception(f"Anthropic 모델 조회 실패: {res.text}")
        except Exception as e:
            logger.error(f"Anthropic 모델 조회 중 오류 발생: {e}")
            raise

    @classmethod
    def build_verification_prompt(cls, factsheet: str) -> str:
        """팩트시트를 포함한 검증용 시스템 프롬프트 생성 헬퍼."""
        return _VERIFICATION_INSTRUCTION.format(factsheet=factsheet)
