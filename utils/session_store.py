"""다중 프로젝트(Workspace) 세션 저장/복원 엔진.

기존 단일 `session_progress.json` 구조를 폐기하고, 프로필별·프로젝트별로
독립된 저장 경로를 사용한다:

    data/projects/{profile_name}/{project_id}/session.json

- project_id는 '타임스탬프_UUID조각' 형태로 발급되어 충돌이 없다.
- '현재 활성 프로젝트'는 모듈 상태(_active)로 관리되며, save/load는 항상
  활성 프로젝트의 session.json을 대상으로 동작한다 (활성 프로젝트가 없으면 no-op).
- 구버전 단일 세션 파일(session_progress.json)이 발견되면 프로필의 프로젝트로
  1회 자동 이관(migrate_legacy_session)한다.

주의: 글로벌 도서 캐시(book_cache.json)는 여러 프로젝트가 공유하는
독립 자산이므로 프로젝트 세션에 포함하지 않는다 (관심사 분리).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

SCHEMA_NAME = "ai_screening_session"
SCHEMA_VERSION = 1

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 다중 프로젝트 루트: data/projects/{profile_name}/{project_id}/session.json
PROJECTS_ROOT = os.path.join(_BASE_DIR, "data", "projects")

# [폐기] 구버전 단일 세션 파일 — 자동 이관(migrate_legacy_session) 전용으로만 참조한다.
LEGACY_SESSION_FILE_PATH = os.path.join(_BASE_DIR, "session_progress.json")

# 현재 활성 프로젝트 (없으면 저장/로드가 모두 안전하게 no-op)
_active: dict[str, Optional[str]] = {"profile": None, "project_id": None, "name": None, "created_at": None}

_UNSAFE_PATH_RE = re.compile(r'[\\/:*?"<>|.]')


def _safe_segment(name: str) -> str:
    """프로필명 등을 파일 시스템 안전 문자열로 정규화한다 (경로 탈출 방지)."""
    cleaned = _UNSAFE_PATH_RE.sub("_", (name or "").strip())
    return cleaned or "default"


def project_dir(profile: str, project_id: str) -> str:
    return os.path.join(PROJECTS_ROOT, _safe_segment(profile), _safe_segment(project_id))


def session_path(profile: str, project_id: str) -> str:
    return os.path.join(project_dir(profile, project_id), "session.json")


# -------------------------------------------------------------
# 활성 프로젝트 관리
# -------------------------------------------------------------
def set_active_project(profile: str, project_id: str, name: str = "", created_at: str = "") -> None:
    _active["profile"] = profile
    _active["project_id"] = project_id
    _active["name"] = name or project_id
    _active["created_at"] = created_at
    logger.info("활성 프로젝트 전환: %s / %s (%s)", profile, project_id, _active["name"])


def clear_active_project() -> None:
    _active["profile"] = None
    _active["project_id"] = None
    _active["name"] = None
    _active["created_at"] = None


def get_active_project() -> Optional[dict]:
    """활성 프로젝트 메타를 반환한다. 활성 프로젝트가 없으면 None."""
    if not _active["profile"] or not _active["project_id"]:
        return None
    return dict(_active)


def active_project_dir() -> Optional[str]:
    if not _active["profile"] or not _active["project_id"]:
        return None
    return project_dir(_active["profile"], _active["project_id"])


def active_session_path() -> Optional[str]:
    d = active_project_dir()
    return os.path.join(d, "session.json") if d else None


# -------------------------------------------------------------
# 저장 / 로드 (항상 '활성 프로젝트' 대상)
# -------------------------------------------------------------
def _build_payload(results: list[dict], cost_summary: dict | None, status: str) -> dict:
    return {
        "schema": SCHEMA_NAME,
        "version": SCHEMA_VERSION,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": status,
        "project": {
            "id": _active["project_id"],
            "name": _active["name"],
            "created_at": _active["created_at"],
        },
        "cost_summary": cost_summary or {},
        "results": results,
    }


def _atomic_write(path: str, payload: dict) -> bool:
    tmp_path = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        return True
    except OSError as e:
        logger.error("세션 파일 저장 실패 (%s): %s", path, e)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False


def save_session_progress(results: list[dict], cost_summary: dict | None = None,
                          status: str = "") -> bool:
    """현재 스냅샷을 '활성 프로젝트'의 session.json에 원자적으로 덮어쓴다.

    활성 프로젝트가 없으면 경고 후 False (크래시 없이 무시 — Guard Clause).
    """
    path = active_session_path()
    if not path:
        logger.warning("활성 프로젝트가 없어 세션 저장을 건너뜁니다 (먼저 프로젝트를 선택하세요).")
        return False
    return _atomic_write(path, _build_payload(results, cost_summary, status))


def load_session_progress(profile: Optional[str] = None,
                          project_id: Optional[str] = None) -> Optional[dict]:
    """지정 프로젝트(미지정 시 활성 프로젝트)의 세션 스냅샷을 로드한다. 없거나 손상 시 None."""
    if profile and project_id:
        path = session_path(profile, project_id)
    else:
        path = active_session_path()
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        return parse_session_payload(raw.encode("utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("프로젝트 세션 로드 실패 (%s): %s", path, e)
        return None


def parse_session_payload(raw_bytes: bytes) -> dict:
    """업로드/로드된 세션 파일을 검증·파싱한다.

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


def session_file_info() -> dict:
    """UI 상단 표기용: 활성 프로젝트의 저장 파일명·경로·최종 저장 시각·학생 수."""
    path = active_session_path()
    info: dict[str, Any] = {
        "filename": os.path.basename(path) if path else None,
        "path": path,
        "exists": bool(path and os.path.exists(path)),
        "saved_at": None,
        "student_count": 0,
        "project_id": _active["project_id"],
        "project_name": _active["name"],
    }
    if info["exists"]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            info["saved_at"] = data.get("saved_at")
            info["student_count"] = len(data.get("results", []))
        except (OSError, json.JSONDecodeError):
            pass
    return info


# -------------------------------------------------------------
# 프로젝트 CRUD
# -------------------------------------------------------------
def create_project(profile: str, name: str) -> dict:
    """새 프로젝트를 생성하고 초기화된 빈 세션 파일을 기록한다."""
    project_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    created_at = time.strftime("%Y-%m-%d %H:%M:%S")
    path = session_path(profile, project_id)
    payload = {
        "schema": SCHEMA_NAME,
        "version": SCHEMA_VERSION,
        "saved_at": created_at,
        "status": "created",
        "project": {"id": project_id, "name": name, "created_at": created_at},
        "cost_summary": {},
        "results": [],
    }
    if not _atomic_write(path, payload):
        raise OSError(f"프로젝트 세션 파일 생성 실패: {path}")
    logger.info("새 프로젝트 생성: %s / %s (%s)", profile, project_id, name)
    return {"project_id": project_id, "name": name, "created_at": created_at,
            "saved_at": created_at, "status": "created", "student_count": 0}


def list_projects(profile: str) -> list[dict]:
    """프로필의 프로젝트 목록을 요약 정보와 함께 반환한다 (생성일 내림차순)."""
    root = os.path.join(PROJECTS_ROOT, _safe_segment(profile))
    if not os.path.isdir(root):
        return []
    projects = []
    for entry in os.listdir(root):
        spath = os.path.join(root, entry, "session.json")
        if not os.path.isfile(spath):
            continue
        summary = {
            "project_id": entry,
            "name": entry,
            "created_at": "",
            "saved_at": "",
            "status": "",
            "student_count": 0,
        }
        try:
            with open(spath, "r", encoding="utf-8") as f:
                data = json.load(f)
            meta = data.get("project") or {}
            summary["name"] = meta.get("name") or entry
            summary["created_at"] = meta.get("created_at") or ""
            summary["saved_at"] = data.get("saved_at") or ""
            summary["status"] = data.get("status") or ""
            summary["student_count"] = len(data.get("results", []))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("프로젝트 요약 읽기 실패 (%s): %s — 손상 항목으로 표시", spath, e)
            summary["status"] = "corrupted"
        projects.append(summary)
    projects.sort(key=lambda p: p.get("created_at") or p["project_id"], reverse=True)
    return projects


def delete_project(profile: str, project_id: str) -> bool:
    """프로젝트 폴더(세션·체크포인트 포함)를 완전히 삭제한다."""
    d = project_dir(profile, project_id)
    if not os.path.isdir(d):
        return False
    try:
        shutil.rmtree(d)
        logger.info("프로젝트 삭제 완료: %s / %s", profile, project_id)
        return True
    except OSError as e:
        logger.error("프로젝트 삭제 실패 (%s): %s", d, e)
        return False


def migrate_legacy_session(profile: str) -> Optional[dict]:
    """구버전 단일 session_progress.json을 발견하면 프로필의 프로젝트로 1회 자동 이관한다.

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

    meta = create_project(profile, "이전 세션 (자동 이관)")
    path = session_path(profile, meta["project_id"])
    payload = {
        "schema": SCHEMA_NAME,
        "version": SCHEMA_VERSION,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "migrated",
        "project": {"id": meta["project_id"], "name": meta["name"], "created_at": meta["created_at"]},
        "cost_summary": data.get("cost_summary", {}),
        "results": data.get("results", []),
    }
    if not _atomic_write(path, payload):
        return None
    meta["student_count"] = len(payload["results"])

    try:
        os.replace(LEGACY_SESSION_FILE_PATH, LEGACY_SESSION_FILE_PATH + ".migrated")
    except OSError as e:
        logger.warning("구버전 세션 파일 백업 실패 (다음 조회 시 중복 이관 가능): %s", e)

    logger.info("구버전 단일 세션 → 프로젝트 '%s' 자동 이관 완료 (%d명).", meta["name"], meta["student_count"])
    return meta
