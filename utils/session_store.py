"""다중 프로젝트(Workspace) 세션 저장/복원 엔진 — Supabase DB 기반.

구 버전의 로컬 파일 구조(data/projects/{profile}/{id}/session.json,
screening_results.jsonl)를 전면 폐기하고 모든 상태를 DB에 저장한다:

    projects    테이블: 프로젝트 메타 + 세션 스냅샷(results, cost_summary)
    checkpoints 테이블: 학생 1명 단위 완료 체크포인트 (Resume 엔진용)

- 함수 시그니처는 구 버전과 호환을 유지하되, 사용자 식별자는
  프로필명(문자열) 대신 users.id(uuid 문자열)를 받는다.
- '현재 활성 프로젝트'는 모듈 상태(_active)로 관리된다. 저장/로드는 항상
  활성 프로젝트를 대상으로 동작한다 (활성 프로젝트가 없으면 no-op).
- 구버전 단일 session_progress.json이 로컬에 남아 있으면 1회 자동
  이관(migrate_legacy_session)하여 DB 프로젝트로 옮긴다 (로컬 실행 전용).

주의: 글로벌 도서 팩트시트 캐시는 factsheets 테이블로 분리되어 있으며
여러 사용자·프로젝트가 공유한다 (관심사 분리).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Optional

from database import DatabaseError, db_delete, db_select, db_select_one, db_upsert

logger = logging.getLogger(__name__)

SCHEMA_NAME = "ai_screening_session"
SCHEMA_VERSION = 1

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# [폐기] 구버전 단일 세션 파일 — 자동 이관(migrate_legacy_session) 전용으로만 참조한다.
LEGACY_SESSION_FILE_PATH = os.path.join(_BASE_DIR, "session_progress.json")

# 현재 활성 프로젝트 (없으면 저장/로드가 모두 안전하게 no-op)
# user_id: users.id (uuid 문자열)
_active: dict[str, Optional[str]] = {"user_id": None, "project_id": None, "name": None, "created_at": None}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# -------------------------------------------------------------
# 활성 프로젝트 관리
# -------------------------------------------------------------
def set_active_project(user_id: str, project_id: str, name: str = "", created_at: str = "") -> None:
    _active["user_id"] = user_id
    _active["project_id"] = project_id
    _active["name"] = name or project_id
    _active["created_at"] = created_at
    logger.info("활성 프로젝트 전환: %s / %s (%s)", user_id, project_id, _active["name"])


def clear_active_project() -> None:
    _active["user_id"] = None
    _active["project_id"] = None
    _active["name"] = None
    _active["created_at"] = None


def get_active_project() -> Optional[dict]:
    """활성 프로젝트 메타를 반환한다. 활성 프로젝트가 없으면 None."""
    if not _active["user_id"] or not _active["project_id"]:
        return None
    return dict(_active)


# -------------------------------------------------------------
# 저장 / 로드 (항상 '활성 프로젝트' 대상)
# -------------------------------------------------------------
def save_session_progress(results: list[dict], cost_summary: dict | None = None,
                          status: str = "") -> bool:
    """현재 스냅샷을 '활성 프로젝트' DB 행에 덮어쓴다.

    활성 프로젝트가 없으면 경고 후 False (크래시 없이 무시 — Guard Clause).
    """
    active = get_active_project()
    if not active:
        logger.warning("활성 프로젝트가 없어 세션 저장을 건너뜁니다 (먼저 프로젝트를 선택하세요).")
        return False
    try:
        db_upsert("projects", {
            "id": active["project_id"],
            "user_id": active["user_id"],
            "name": active["name"] or active["project_id"],
            "status": status or "running",
            "created_at": active["created_at"] or "",
            "saved_at": _now(),
            "cost_summary": cost_summary or {},
            # DB(jsonb)는 datetime 등 비직렬화 객체를 받지 못하므로 str 폴백으로 정규화
            "results": json.loads(json.dumps(results, ensure_ascii=False, default=str)),
        }, on_conflict="user_id,id")
        return True
    except DatabaseError as e:
        logger.error("프로젝트 세션 DB 저장 실패: %s", e)
        return False


def _row_to_payload(row: dict) -> dict:
    """projects 테이블 행 → 구버전 session.json과 동일한 페이로드 구조."""
    return {
        "schema": SCHEMA_NAME,
        "version": SCHEMA_VERSION,
        "saved_at": row.get("saved_at") or "",
        "status": row.get("status") or "",
        "project": {
            "id": row["id"],
            "name": row.get("name") or row["id"],
            "created_at": row.get("created_at") or "",
        },
        "cost_summary": row.get("cost_summary") or {},
        "results": row.get("results") or [],
    }


def load_session_progress(user_id: Optional[str] = None,
                          project_id: Optional[str] = None) -> Optional[dict]:
    """지정 프로젝트(미지정 시 활성 프로젝트)의 세션 스냅샷을 DB에서 로드한다. 없으면 None."""
    if not (user_id and project_id):
        active = get_active_project()
        if not active:
            return None
        user_id, project_id = active["user_id"], active["project_id"]
    try:
        row = db_select_one("projects", {"user_id": user_id, "id": project_id})
    except DatabaseError as e:
        logger.warning("프로젝트 세션 로드 실패 (%s/%s): %s", user_id, project_id, e)
        return None
    return _row_to_payload(row) if row else None


def parse_session_payload(raw_bytes: bytes) -> dict:
    """업로드/로드된 세션 파일을 검증·파싱한다 (파일 공유·이관용 — 구버전과 동일).

    파일 이름과 무관하게 내용 스키마만 검사하므로, 사용자가 파일명을
    임의로 바꿔서 옮겨도 복원이 가능하다. 실패 시 ValueError(사유 포함).
    """
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            text = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("파일 인코딩을 해석할 수 없습니다 (UTF-8/CP949 지원).")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 파싱 실패: {e}")

    if not isinstance(data, dict):
        raise ValueError("최상위 구조가 JSON 객체가 아닙니다.")
    if data.get("schema") != SCHEMA_NAME:
        raise ValueError(
            f"스키마 불일치: 이 파일은 '{data.get('schema')}' 형식입니다 "
            f"(기대값: '{SCHEMA_NAME}')."
        )
    version = data.get("version")
    if not isinstance(version, int) or version > SCHEMA_VERSION:
        raise ValueError(f"지원하지 않는 스키마 버전입니다: {version}")

    results = data.get("results")
    if not isinstance(results, list):
        raise ValueError("'results' 필드가 리스트가 아닙니다.")

    # 각 레코드 최소 필드 검증 (student 키만 필수 — 나머지는 관대하게 수용)
    valid_results = [r for r in results if isinstance(r, dict) and r.get("student")]
    if results and not valid_results:
        raise ValueError("유효한 학생 레코드(student 필드)가 하나도 없습니다.")

    data["results"] = valid_results
    return data


def export_session_payload() -> Optional[str]:
    """활성 프로젝트 세션을 다운로드용 JSON 문자열로 직렬화한다 (타 환경 이관용)."""
    payload = load_session_progress()
    if payload is None:
        return None
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def session_file_info() -> dict:
    """UI 상단 표기용: 활성 프로젝트의 저장 위치(DB)·최종 저장 시각·학생 수."""
    active = get_active_project()
    info: dict[str, Any] = {
        "filename": None,
        "path": "Supabase DB (projects)",
        "exists": False,
        "saved_at": None,
        "student_count": 0,
        "project_id": _active["project_id"],
        "project_name": _active["name"],
    }
    if not active:
        return info
    payload = load_session_progress()
    if payload:
        info["exists"] = True
        info["filename"] = f"{active['name']} (DB)"
        info["saved_at"] = payload.get("saved_at")
        info["student_count"] = len(payload.get("results", []))
    return info


# -------------------------------------------------------------
# 프로젝트 CRUD
# -------------------------------------------------------------
def create_project(user_id: str, name: str) -> dict:
    """새 프로젝트 행을 생성한다 (초기 results는 빈 배열)."""
    project_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    created_at = _now()
    db_upsert("projects", {
        "id": project_id,
        "user_id": user_id,
        "name": name,
        "status": "created",
        "created_at": created_at,
        "saved_at": created_at,
        "cost_summary": {},
        "results": [],
    }, on_conflict="user_id,id")
    logger.info("새 프로젝트 생성: %s / %s (%s)", user_id, project_id, name)
    return {"project_id": project_id, "name": name, "created_at": created_at,
            "saved_at": created_at, "status": "created", "student_count": 0}


def list_projects(user_id: str) -> list[dict]:
    """사용자의 프로젝트 목록을 요약 정보와 함께 반환한다 (생성일 내림차순)."""
    try:
        rows = db_select("projects", {"user_id": user_id},
                         columns="id,name,status,created_at,saved_at,results",
                         order="created_at.desc")
    except DatabaseError as e:
        logger.error("프로젝트 목록 조회 실패: %s", e)
        return []
    projects = []
    for row in rows:
        projects.append({
            "project_id": row["id"],
            "name": row.get("name") or row["id"],
            "created_at": row.get("created_at") or "",
            "saved_at": row.get("saved_at") or "",
            "status": row.get("status") or "",
            "student_count": len(row.get("results") or []),
        })
    return projects


def delete_project(user_id: str, project_id: str) -> bool:
    """프로젝트 행과 체크포인트를 완전히 삭제한다."""
    try:
        db_delete("checkpoints", {"user_id": user_id, "project_id": project_id})
        deleted = db_delete("projects", {"user_id": user_id, "id": project_id})
    except DatabaseError as e:
        logger.error("프로젝트 삭제 실패 (%s/%s): %s", user_id, project_id, e)
        return False
    if deleted:
        logger.info("프로젝트 삭제 완료: %s / %s", user_id, project_id)
        return True
    return False


# -------------------------------------------------------------
# 체크포인트 (구 screening_results.jsonl 대체 — Resume 엔진)
# -------------------------------------------------------------
def load_checkpoint_map(user_id: Optional[str] = None,
                        project_id: Optional[str] = None) -> dict:
    """완료된 [학번_성명] → 레코드 인덱스를 DB에서 로드한다.

    반환 딕셔너리는 루프 진입 전 `if student in completed_map: skip` 판단에
    사용되어 중복 API 호출과 토큰 낭비를 원천 차단한다 (Token Waste Zero).
    """
    if not (user_id and project_id):
        active = get_active_project()
        if not active:
            return {}
        user_id, project_id = active["user_id"], active["project_id"]
    try:
        rows = db_select("checkpoints", {"user_id": user_id, "project_id": project_id},
                         columns="student,record")
    except DatabaseError as e:
        logger.error("체크포인트 로드 실패: %s", e)
        return {}
    return {row["student"]: (row.get("record") or {}) for row in rows if row.get("student")}


def upsert_checkpoint(record: dict) -> bool:
    """피실험자 1명(Atomic Unit)의 최종 결과를 활성 프로젝트 체크포인트에 즉시 영속화한다.

    구버전의 append-only jsonl과 달리 동일 학생 재처리 시 최신 레코드로 갱신(upsert)된다.
    """
    active = get_active_project()
    student = record.get("student")
    if not active or not student:
        logger.warning("활성 프로젝트/학생 키가 없어 체크포인트 저장을 건너뜁니다.")
        return False
    try:
        db_upsert("checkpoints", {
            "user_id": active["user_id"],
            "project_id": active["project_id"],
            "student": student,
            "record": json.loads(json.dumps(record, ensure_ascii=False, default=str)),
        }, on_conflict="user_id,project_id,student")
        return True
    except DatabaseError as e:
        logger.error("체크포인트 저장 실패 (%s): %s", student, e)
        return False


# -------------------------------------------------------------
# 구버전 로컬 파일 → DB 1회 자동 이관 (로컬 실행 전용; Vercel에는 파일이 없어 no-op)
# -------------------------------------------------------------
def migrate_legacy_session(user_id: str) -> Optional[dict]:
    """구버전 단일 session_progress.json을 발견하면 DB 프로젝트로 1회 자동 이관한다.

    이관 성공 시 원본 파일은 .migrated 백업으로 이름을 바꿔 재이관을 방지한다.
    Returns: 이관으로 생성된 프로젝트 요약 dict 또는 None.
    """
    if not os.path.exists(LEGACY_SESSION_FILE_PATH):
        return None
    try:
        with open(LEGACY_SESSION_FILE_PATH, "rb") as f:
            data = parse_session_payload(f.read())
    except (OSError, ValueError) as e:
        logger.warning("구버전 세션 이관 실패 (건너뜀): %s", e)
        return None

    meta = create_project(user_id, "이전 세션 (자동 이관)")
    try:
        db_upsert("projects", {
            "id": meta["project_id"],
            "user_id": user_id,
            "name": meta["name"],
            "status": "migrated",
            "created_at": meta["created_at"],
            "saved_at": _now(),
            "cost_summary": data.get("cost_summary", {}),
            "results": data.get("results", []),
        }, on_conflict="user_id,id")
    except DatabaseError as e:
        logger.error("구버전 세션 DB 이관 실패: %s", e)
        return None
    meta["student_count"] = len(data.get("results", []))

    try:
        os.replace(LEGACY_SESSION_FILE_PATH, LEGACY_SESSION_FILE_PATH + ".migrated")
    except OSError as e:
        logger.warning("구버전 세션 파일 백업 실패 (다음 조회 시 중복 이관 가능): %s", e)

    logger.info("구버전 단일 세션 → DB 프로젝트 '%s' 자동 이관 완료 (%d명).", meta["name"], meta["student_count"])
    return meta
