"""세션 진행 상태 저장/복원 엔진 (State Portability).

`session_progress.json`은 현재 작업 세션(학생 리스트 + 각 Phase별 분석 결과)의
전체 스냅샷이다. 서버가 재기동되어도 이 파일로 마지막 상태를 복원할 수 있고,
파일을 다른 컴퓨터로 복사한 뒤 UI의 [진행 상태 파일 업로드]로 올리면
파일 이름이 변경되었더라도 스키마(schema/version)만 일치하면 이어서 작업할 수 있다.

주의: 글로벌 도서 캐시(book_cache.json)는 여러 사용자·세션이 공유하는
독립 자산이므로 이 세션 파일에 포함하지 않는다 (관심사 분리).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

SCHEMA_NAME = "ai_screening_session"
SCHEMA_VERSION = 1

# 프로젝트 루트(ai_screening/)에 저장 — UI 상단에 이 경로를 상시 표기한다.
SESSION_FILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "session_progress.json",
)


def save_session_progress(results: list[dict], cost_summary: dict | None = None,
                          status: str = "") -> bool:
    """현재 세션 스냅샷을 session_progress.json에 원자적으로 저장한다.

    tmp 파일에 먼저 쓰고 os.replace로 교체하여, 저장 도중 프로세스가
    죽어도 기존 파일이 반파(半破)되지 않도록 보장한다.
    """
    payload = {
        "schema": SCHEMA_NAME,
        "version": SCHEMA_VERSION,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": status,
        "cost_summary": cost_summary or {},
        "results": results,
    }
    tmp_path = SESSION_FILE_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, SESSION_FILE_PATH)
        return True
    except OSError as e:
        logger.error("session_progress.json 저장 실패: %s", e)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False


def load_session_progress() -> Optional[dict]:
    """앱 기동 시 마지막 세션 스냅샷을 로드한다. 없거나 손상 시 None."""
    if not os.path.exists(SESSION_FILE_PATH):
        return None
    try:
        with open(SESSION_FILE_PATH, "r", encoding="utf-8") as f:
            raw = f.read()
        return parse_session_payload(raw.encode("utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("session_progress.json 로드 실패 (무시하고 새 세션 시작): %s", e)
        return None


def parse_session_payload(raw_bytes: bytes) -> dict:
    """업로드된 진행 상태 파일을 검증·파싱한다.

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
    """UI 상단 표기용: 현재 저장 파일명·경로·최종 저장 시각·학생 수."""
    info: dict[str, Any] = {
        "filename": os.path.basename(SESSION_FILE_PATH),
        "path": SESSION_FILE_PATH,
        "exists": os.path.exists(SESSION_FILE_PATH),
        "saved_at": None,
        "student_count": 0,
    }
    if info["exists"]:
        try:
            with open(SESSION_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            info["saved_at"] = data.get("saved_at")
            info["student_count"] = len(data.get("results", []))
        except (OSError, json.JSONDecodeError):
            pass
    return info
