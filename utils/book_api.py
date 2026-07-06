"""네이버 책 검색 OpenAPI 연동 모듈 (Zero-Token 도서 메타데이터 확정).

기존 LLM 기반 저자 역추적(lookup_author)을 완전히 대체한다.
- 도서명으로 네이버 책 검색 API를 호출하여 공식 서지 정보(정제 도서명/저자/출판사)를 확정한다.
- LLM API를 전혀 사용하지 않으므로 토큰 소모가 0이다.

[API 키 로드 정책]
NAVER_CLIENT_ID / NAVER_CLIENT_SECRET은 반드시 os.getenv()로 .env(환경 변수)에서
직접 읽는다. user_manager(프로필)나 프론트엔드 UI에는 절대 연동하지 않는다.
표준 라이브러리(urllib)만 사용하여 추가 의존성이 없다.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

NAVER_BOOK_API_URL = "https://openapi.naver.com/v1/search/book.json"

_TAG_RE = re.compile(r"<[^>]+>")

# 키 미설정 경고는 최초 1회만 출력 (매 도서마다 로그가 도배되지 않도록)
_missing_key_warned = False


def _clean_field(raw: Optional[str]) -> str:
    """네이버 응답 필드 정제: <b> 등 HTML 태그 제거 + 엔티티 복원 + 트림."""
    if not raw:
        return ""
    return html.unescape(_TAG_RE.sub("", raw)).strip()


def _normalize_for_match(title: str) -> str:
    """도서명 매칭용 정규화 (stage3_verify._normalize_title과 동일 규칙: 한글/영숫자만, 소문자)."""
    normalized = unicodedata.normalize("NFC", title or "")
    normalized = re.sub(r"[^\w가-힣a-zA-Z0-9]", "", normalized)
    return normalized.lower()


def naver_book_search(query: str, display: int = 5, timeout: float = 5.0) -> list[dict]:
    """네이버 책 검색 API를 HTTP로 호출하여 정제된 도서 항목 리스트를 반환한다.

    Returns:
        [{"title", "author", "publisher", "pubdate", "isbn"}, ...] — 실패/키 미설정 시 [].
    """
    global _missing_key_warned

    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        if not _missing_key_warned:
            logger.warning(
                "NAVER_CLIENT_ID / NAVER_CLIENT_SECRET이 .env에 설정되지 않았습니다. "
                "네이버 책 검색(Zero-Token 저자 확정)이 비활성화되어 저자가 'Unknown'으로 처리됩니다."
            )
            _missing_key_warned = True
        return []

    url = f"{NAVER_BOOK_API_URL}?query={urllib.parse.quote(query)}&display={display}"
    request = urllib.request.Request(url, headers={
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    })

    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        logger.error("네이버 책 검색 API HTTP 에러 (%s): %s", e.code, e.reason)
        return []
    except Exception as e:
        logger.error("네이버 책 검색 API 호출 실패: %s", e)
        return []

    items = []
    for it in data.get("items", []):
        items.append({
            "title": _clean_field(it.get("title")),
            # 네이버는 복수 저자를 '^'로 구분한다 → "저자1, 저자2"로 변환
            "author": _clean_field(it.get("author")).replace("^", ", "),
            "publisher": _clean_field(it.get("publisher")),
            "pubdate": _clean_field(it.get("pubdate")),
            "isbn": _clean_field(it.get("isbn")),
        })
    return items


def lookup_book_metadata(book_title: str) -> Optional[dict]:
    """도서명으로 공식 서지 메타데이터(정제 도서명/저자)를 확정한다 (Data Sanitization).

    매칭 우선순위:
      1) 정규화 도서명이 완전 일치하고 저자가 있는 항목
      2) 검색어가 결과 도서명에 포함(부제/캐치프레이즈 차이)되고 저자가 있는 항목
      3) 첫 번째 결과 (저자가 있을 때만)

    Returns:
        {"title", "author", "publisher", "pubdate", "isbn"} 또는 None (미검색/실패).
    """
    if not book_title or not book_title.strip() or book_title.strip().lower() == "unknown":
        return None

    items = naver_book_search(book_title.strip())
    if not items:
        return None

    target = _normalize_for_match(book_title)

    for item in items:
        if item["author"] and _normalize_for_match(item["title"]) == target:
            return item
    if target:
        for item in items:
            if item["author"] and target in _normalize_for_match(item["title"]):
                return item
    return items[0] if items[0]["author"] else None
