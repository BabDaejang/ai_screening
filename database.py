"""Supabase(PostgREST) 데이터베이스 연결 모듈.

supabase-py 대신 httpx로 PostgREST REST API를 직접 호출하는 경량 클라이언트.
(anthropic/openai SDK가 이미 httpx에 의존하므로 신규 의존성 충돌이 없다.)

환경 변수 (로컬: .env / 배포: Vercel Environment Variables):
    SUPABASE_URL              예: https://pqzcviurfjzsgkmaprqe.supabase.co
    SUPABASE_SERVICE_ROLE_KEY 서버 전용 service_role 키 (절대 클라이언트 노출 금지)

스키마는 db/schema.sql 참조 (Supabase SQL Editor에서 1회 실행).
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """DB 통신/쿼리 실패. 호출부는 이 예외 하나만 처리하면 된다."""


_client_lock = threading.Lock()
_client: Optional[httpx.Client] = None


def _base_url() -> str:
    url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    if not url:
        raise DatabaseError("SUPABASE_URL 환경 변수가 설정되지 않았습니다.")
    return f"{url}/rest/v1"


def _service_key() -> str:
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY") or ""
    if not key:
        raise DatabaseError("SUPABASE_SERVICE_ROLE_KEY 환경 변수가 설정되지 않았습니다.")
    return key


def get_client() -> httpx.Client:
    """프로세스 전역 httpx 클라이언트 (커넥션 재사용). 서버리스에서도 안전하다."""
    global _client
    with _client_lock:
        if _client is None or _client.is_closed:
            key = _service_key()
            _client = httpx.Client(
                base_url=_base_url(),
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(15.0, connect=10.0),
            )
        return _client


def _filters_to_params(filters: Optional[dict]) -> dict:
    """{"col": value} → PostgREST eq 필터 쿼리 파라미터로 변환."""
    params: dict[str, str] = {}
    for col, val in (filters or {}).items():
        params[col] = f"eq.{val}"
    return params


def _request(method: str, table: str, *, params: Optional[dict] = None,
             json_body: Any = None, headers: Optional[dict] = None) -> list:
    try:
        res = get_client().request(method, f"/{table}", params=params,
                                   json=json_body, headers=headers)
    except httpx.HTTPError as e:
        raise DatabaseError(f"DB 통신 실패 ({method} {table}): {e}") from e

    if res.status_code >= 400:
        raise DatabaseError(f"DB 쿼리 실패 ({method} {table}, HTTP {res.status_code}): {res.text[:500]}")
    if not res.content:
        return []
    try:
        data = res.json()
    except ValueError:
        return []
    return data if isinstance(data, list) else [data]


# -------------------------------------------------------------
# CRUD 헬퍼 — 모든 상위 모듈(user_manager/session_store/app)이 사용하는 유일한 통로
# -------------------------------------------------------------
def db_select(table: str, filters: Optional[dict] = None, columns: str = "*",
              order: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
    """SELECT. order 예: 'created_at.desc'"""
    params = _filters_to_params(filters)
    params["select"] = columns
    if order:
        params["order"] = order
    if limit is not None:
        params["limit"] = str(limit)
    return _request("GET", table, params=params)


def db_select_one(table: str, filters: dict, columns: str = "*") -> Optional[dict]:
    rows = db_select(table, filters, columns=columns, limit=1)
    return rows[0] if rows else None


def db_insert(table: str, row: dict) -> dict:
    rows = _request("POST", table, json_body=row,
                    headers={"Prefer": "return=representation"})
    if not rows:
        raise DatabaseError(f"INSERT 결과가 비어 있습니다 ({table}).")
    return rows[0]


def db_upsert(table: str, row: dict, on_conflict: Optional[str] = None) -> dict:
    """INSERT ... ON CONFLICT DO UPDATE. on_conflict 예: 'user_id,project_id,student'"""
    params = {"on_conflict": on_conflict} if on_conflict else None
    rows = _request("POST", table, params=params, json_body=row,
                    headers={"Prefer": "resolution=merge-duplicates,return=representation"})
    if not rows:
        raise DatabaseError(f"UPSERT 결과가 비어 있습니다 ({table}).")
    return rows[0]


def db_update(table: str, filters: dict, values: dict) -> list[dict]:
    if not filters:
        raise DatabaseError(f"UPDATE에는 필터가 필수입니다 ({table}) — 전체 갱신 방지.")
    return _request("PATCH", table, params=_filters_to_params(filters),
                    json_body=values, headers={"Prefer": "return=representation"})


def db_delete(table: str, filters: dict) -> list[dict]:
    if not filters:
        raise DatabaseError(f"DELETE에는 필터가 필수입니다 ({table}) — 전체 삭제 방지.")
    return _request("DELETE", table, params=_filters_to_params(filters),
                    headers={"Prefer": "return=representation"})


def check_connection() -> bool:
    """기동 시 헬스체크용: users 테이블에 최소 쿼리를 날려 연결을 검증한다."""
    try:
        db_select("users", columns="id", limit=1)
        return True
    except DatabaseError as e:
        logger.error("Supabase 연결 확인 실패: %s", e)
        return False
