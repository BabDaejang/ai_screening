from dotenv import load_dotenv
load_dotenv() # .env 로드

import asyncio
import csv
import io
import json
import logging
import os
import re
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from utils.user_manager import UserManager
from utils.cost_tracker import CostTracker
from utils.docx_metadata import extract_docx_metadata
from utils.file_reader import read_submissions, strip_float_tail
from utils.book_api import lookup_book_metadata
from utils.report_generator import generate_csv, generate_report, calculate_tiers
from utils.session_store import (
    save_session_progress,
    load_session_progress,
    parse_session_payload,
    session_file_info,
    create_project,
    list_projects,
    delete_project,
    set_active_project,
    clear_active_project,
    get_active_project,
    active_project_dir,
    active_session_path,
    migrate_legacy_session,
)
from providers import create_provider
from stages.stage1_rules import run_stage1
from stages.stage2_screening import run_stage2
from stages.stage3_verify import run_stage3, ensure_factsheet, _normalize_title

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="AI 의심 선별 도구 웹 UI")

# 전역 상태 관리
analysis_state = {
    "status": "idle",  # idle, running, completed, error, paused, awaiting_phase, awaiting_stage3_selection, stopped
    "progress": 0,
    "step": "",
    "logs": [],
    "results": [],
    "cost_summary": {},
    "error_message": "",
    "awaiting_phase": None,  # None | "phase2" | "phase3" — [다음 단계 진행] 버튼 게이팅용
    "stage3_selection": None,  # awaiting_stage3_selection 상태에서 듀얼 패널 모달용 후보 페이로드
    # JIT 팩트시트(Cache Miss) 생성 중인 도서명 — UI 로딩 스피너 "'{도서명}' 팩트시트 신규 생성 중..." 표시용
    "factsheet_generating": None,
}

# 락 객체 및 실행 제어 이벤트
state_lock = threading.Lock()
# book_cache.json 공유 딕셔너리/파일 보호용 락:
# Phase 1.5 백그라운드 선제 생성 스레드와 메인 파이프라인(JIT 생성),
# 온디맨드 보강(enrich) 엔드포인트가 동시에 load-modify-save 하는 것을 직렬화한다.
book_cache_lock = threading.Lock()
stop_event = threading.Event()
pause_event = threading.Event()
pause_event.set()
phase_gate_event = threading.Event()

# 3단계 사용자 주도형 대상 선택 게이트 (듀얼 패널 모달의 [최종 검증 확정]이 해제)
stage3_selection_event = threading.Event()
stage3_selected = {"keys": None}  # 사용자가 확정한 학생 키 목록

# 단계별 명칭 (Task 5 게이팅 UI에 표시)
_PHASE_LABELS = {
    "phase2": "2단계: AI 문체 스크리닝 (토큰 소비)",
    "phase3": "3단계: 사실 검증 (토큰 소비)",
}

def wait_for_phase_gate(phase_key: str):
    """단계 경계 게이팅(Task 3/5): 이전 단계가 완전히 끝난 뒤 자동으로 정지하고,
    사용자가 [다음 단계 진행] 버튼을 클릭해야만 다음 단계로 진입을 허가한다.
    토큰을 소비하는 단계(2/3단계)에 진입하기 전 반드시 이 게이트를 통과해야 하므로,
    stage1_rules(토큰 비소비)를 생략하고 곧바로 다음 단계로 진입하는 경로가 원천 차단된다.
    """
    phase_label = _PHASE_LABELS.get(phase_key, phase_key)
    phase_gate_event.clear()
    with state_lock:
        analysis_state["status"] = "awaiting_phase"
        analysis_state["awaiting_phase"] = phase_key
        analysis_state["step"] = f"[대기] {phase_label} 진입 대기 중 — [다음 단계 진행] 버튼을 클릭하세요."
    add_log(f"⏸️ {phase_label} 진입 대기 중입니다. [다음 단계 진행] 버튼을 클릭해 주세요.")

    # [Guard — Idle State Security] 이 대기 루프는 threading.Event 상태 확인만 반복하는
    # 순수 이벤트 대기다. LLM API 호출·파일 IO·무거운 연산이 전혀 없으므로, 대기 상태
    # (phase_status == 'awaiting_phase')에서는 UI 폴링/리렌더링과 무관하게 토큰 소모 0이
    # 보장된다. 게이트 해제(phase_gate_event.set)는 오직 사용자의 [다음 단계 진행] 버튼
    # onClick → POST /api/analyze/next-phase 이벤트 핸들러에서만 발생한다 (Trigger Isolation).
    while not phase_gate_event.is_set():
        if stop_event.is_set():
            raise Exception("사용자에 의해 분석이 강제 종료되었습니다.")
        phase_gate_event.wait(timeout=1.0)

    with state_lock:
        analysis_state["status"] = "running"
        analysis_state["awaiting_phase"] = None
    add_log(f"▶️ 사용자 확인 완료 — {phase_label} 시작.")

def wait_for_stage3_selection(candidates_payload: list, preselected_keys: list) -> list:
    """3단계(토큰 소비) 진입 전 '사용자 주도형 대상 확정' 게이트.

    [3단계 시작] 시 즉시 LLM을 호출하지 않고, 듀얼 패널(Transfer List) 모달에서
    사용자가 [최종 검증 확정]을 누를 때까지 대기한다. 대기 중에는 어떤 API도
    호출되지 않으므로 토큰 소모는 0이다. 모달 로딩 시 preselected_keys(1·2단계
    분석 결과가 임계치를 초과한 위험군)가 미리 체크된 상태로 초기화된다.

    Returns:
        사용자가 확정한 학생 키 목록.
    """
    stage3_selection_event.clear()
    stage3_selected["keys"] = None
    with state_lock:
        analysis_state["status"] = "awaiting_stage3_selection"
        analysis_state["awaiting_phase"] = "phase3"
        analysis_state["stage3_selection"] = {
            "candidates": candidates_payload,
            "preselected": preselected_keys,
        }
        analysis_state["step"] = "[대기] 3단계 심층 검증 대상 선택 대기 중 — [3단계 대상 선택] 창에서 확정하세요."
    add_log(
        f"⏸️ 3단계 진입 대기 — 듀얼 패널 창에서 검증 대상을 확정해 주세요. "
        f"(위험군 {len(preselected_keys)}명 자동 선택됨 / 확정 전까지 API 호출·토큰 소모 0)"
    )

    while not stage3_selection_event.is_set():
        if stop_event.is_set():
            raise Exception("사용자에 의해 분석이 강제 종료되었습니다.")
        stage3_selection_event.wait(timeout=1.0)

    with state_lock:
        analysis_state["status"] = "running"
        analysis_state["awaiting_phase"] = None
        analysis_state["stage3_selection"] = None
    selected = list(stage3_selected["keys"] or [])
    add_log(f"▶️ 사용자 확정 완료 — 3단계 심층 검증 대상 {len(selected)}명을 Batch로 검증합니다.")
    return selected

def check_control_state(stage_name: str, current_idx: int, total_count: int, item_id: str):
    if stop_event.is_set():
        raise Exception("사용자에 의해 분석이 강제 종료되었습니다.")
        
    step_msg = f"[{stage_name}] ({current_idx}/{total_count}) {item_id} 스크리닝 중…"
    if "3단계" in stage_name:
        step_msg = step_msg.replace("스크리닝 중…", "검증 중…")
        
    if "1단계" in stage_name:
        progress = 25 + int((current_idx / total_count) * 20)
    elif "2단계" in stage_name:
        progress = 45 + int((current_idx / total_count) * 25)
    else:
        progress = 70 + int((current_idx / total_count) * 30)
        
    update_progress(progress, step_msg)
    
    if not pause_event.is_set():
        add_log(f"⏸️ 분석이 일시정지되었습니다. (현재 대기 항목: {item_id})")
        with state_lock:
            analysis_state["status"] = "paused"
        while not pause_event.is_set():
            if stop_event.is_set():
                raise Exception("사용자에 의해 분석이 강제 종료되었습니다.")
            pause_event.wait(timeout=1.0)
        with state_lock:
            analysis_state["status"] = "running"
        add_log("▶️ 분석이 재개되었습니다.")

def add_log(message: str):
    with state_lock:
        logger.info(message)
        analysis_state["logs"].append(message)

def update_progress(progress: int, step: str):
    with state_lock:
        analysis_state["progress"] = progress
        analysis_state["step"] = step

# -------------------------------------------------------------
# API 모델 정의
# -------------------------------------------------------------
class ProfileCreateRequest(BaseModel):
    name: str

class ApiKeyRegisterRequest(BaseModel):
    provider: str
    api_key: str

class ApiKeyBatchRequest(BaseModel):
    gemini: Optional[str] = None
    anthropic: Optional[str] = None
    openai: Optional[str] = None

class LoginRequest(BaseModel):
    name: str

class ModelSelectRequest(BaseModel):
    screening_provider: str
    screening_model: str
    verify_provider: str
    verify_model: str

class AnalyzeRequest(BaseModel):
    # [Deprecated] 파일 읽기는 POST /api/data/import로 분리되었다.
    # 파이프라인은 메모리 데이터셋만 순회하므로 이 필드는 더 이상 사용되지 않는다 (하위 호환용).
    submissions_dir: str = ""
    verify_all: bool = False
    no_verify: bool = False
    no_web: bool = False
    
    # 동적 모델/프로바이더 선택
    screening_provider: str
    screening_model: str
    verify_provider: str
    verify_model: str

class RefreshConfigRequest(BaseModel):
    provider: Optional[str] = None

class EnrichRequest(BaseModel):
    book_title: str
    author: str
    verify_provider: Optional[str] = None
    verify_model: Optional[str] = None

# -------------------------------------------------------------
# 단일 마스터 파일 기반 도서 정보 캐시 엔진 (book_cache.json)
# -------------------------------------------------------------
def load_book_cache() -> dict:
    """book_cache.json 마스터 파일에서 캐시 딕셔너리를 로드합니다. 손상 시 빈 딕셔너리를 반환합니다."""
    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "book_cache.json")
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"book_cache.json 로드 실패 (손상 가능성), 신규 생성: {e}")
        return {}

def save_book_cache(cache_data: dict):
    """book_cache.json 마스터 파일에 캐시 딕셔너리를 안전하게 저장합니다 (Write-Through: flush+fsync)."""
    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "book_cache.json")
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
    except OSError as e:
        logger.error(f"book_cache.json 저장 실패: {e}")

def normalize_cache_key(title: str, author: str) -> str:
    """공백 및 파일 시스템 금지 문자를 제거하여 고유 키를 정형화합니다."""
    cleaned_title = re.sub(r'[\s\\/:*?"<>|]', '', title).strip()
    cleaned_author = re.sub(r'[\s\\/:*?"<>|]', '', author).strip()
    return f"{cleaned_title}_{cleaned_author}"

def find_cached_book_entry_by_title(book_title: str, book_cache: dict) -> Optional[tuple]:
    """도서명만으로 book_cache.json의 기존 엔트리를 탐색한다 (title-first 폴백).

    캐시 키는 '도서명_저자명' 조합이라서 저자가 미상이면 키 조회가 불가능하다.
    도서명 정규화 일치로 기존 엔트리를 먼저 찾아 저자·팩트시트를 재사용하면
    캐시 히트 시 외부 API(네이버 책 검색) 호출조차 생략된다.

    Returns:
        (cache_key, entry) 또는 None.
    """
    target = _normalize_title(book_title or "")
    if not target:
        return None
    for cache_key, entry in book_cache.items():
        if _normalize_title(entry.get("book_title", "") or "") == target:
            return cache_key, entry
    return None

# -------------------------------------------------------------
# 학생 레코드 식별자 정제 & 중복 판정 (메모리 데이터셋 공통 유틸)
# -------------------------------------------------------------
def sanitize_student_identity(record: dict) -> bool:
    """레코드의 student_id/student_name/student(복합키)에서 Excel Float 캐스팅으로
    붙은 후미 '.0' 꼬리표를 제거한다 (예: '10701.0' → '10701').

    Returns:
        정제로 인해 값이 하나라도 변경되었으면 True (마이그레이션 저장 판단용).
    """
    changed = False
    for field in ("student_id", "student_name"):
        raw = record.get(field)
        if raw is None:
            continue
        cleaned = strip_float_tail(raw)
        if cleaned != str(raw):
            record[field] = cleaned
            changed = True
    student = record.get("student")
    if student:
        # 복합키('학번_이름')의 각 세그먼트를 개별 정제 — 순수 숫자+'.0' 형태만 변경되므로 안전
        cleaned_key = "_".join(strip_float_tail(part) for part in str(student).split("_"))
        if cleaned_key != str(student):
            record["student"] = cleaned_key
            changed = True
    return changed

def student_dedupe_key(record: dict) -> str:
    """Smart Append 중복 판정 키: 학번이 있으면 학번 기준, 없으면 이름 기준."""
    sid = strip_float_tail(record.get("student_id") or "")
    if sid:
        return f"id:{sid}"
    name = str(record.get("student_name") or record.get("student") or "").strip()
    return f"nm:{name}"

def _pipeline_busy() -> bool:
    """호출 전 state_lock을 잡은 상태에서 사용할 것: 파이프라인이 데이터셋을 순회 중인지 판정."""
    return analysis_state["status"] in ("running", "paused", "awaiting_phase", "awaiting_stage3_selection")

# '도서명(저자명)' 또는 '도서명[저자명]' 복합 텍스트에서 후미 괄호를 캡처한다.
_TITLE_AUTHOR_PATTERN = re.compile(r'^(.+?)\s*[\(\[](.+?)[\)\]]$')

def parse_book_title_author(raw_title: Optional[str]) -> tuple[str, Optional[str]]:
    """'도서명(저자명)' 형태의 복합 텍스트를 도서명/저자명으로 분리한다.

    괄호/대괄호가 없거나 정규식 매칭에 실패하면 원본 문자열을 그대로 도서명으로
    반환하고 저자는 None으로 반환한다 (예외 발생 없이 항상 안전하게 폴백).
    """
    if not raw_title:
        return "", None
    try:
        cleaned = raw_title.strip()
        if not cleaned:
            return "", None
        match = _TITLE_AUTHOR_PATTERN.match(cleaned)
        if match:
            title_part = match.group(1).strip()
            author_part = match.group(2).strip()
            if title_part and author_part:
                return title_part, author_part
        return cleaned, None
    except Exception as e:
        logger.warning(f"도서명/저자 분리 정규식 처리 실패 (원본 유지): {e}")
        return (raw_title or "").strip(), None

# -------------------------------------------------------------
# 2단계 스크리닝 결과 Append-Only 영속화 & 체크포인트-재개(Resume) 엔진
# (screening_results.jsonl)
# -------------------------------------------------------------
# [폐기] 구버전 글로벌 체크포인트 경로 — 활성 프로젝트가 없을 때의 폴백으로만 사용
_LEGACY_RESULTS_JSONL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screening_results.jsonl")

def RESULTS_JSONL_PATH_current() -> str:
    """체크포인트(jsonl) 경로: 활성 프로젝트 폴더 내에 프로젝트별로 격리 저장한다.

    프로젝트마다 독립된 체크포인트를 가지므로 서로 다른 프로젝트의
    동명 학생이 잘못 스킵(Resume)되는 교차 오염이 발생하지 않는다.
    """
    d = active_project_dir()
    if d:
        return os.path.join(d, "screening_results.jsonl")
    return _LEGACY_RESULTS_JSONL_PATH

def load_completed_results() -> dict:
    """screening_results.jsonl을 스캔하여 이미 완료된 [학번_성명] 인덱스를 로드합니다.

    손상된 라인은 건너뛰고 계속 진행합니다 (Fault Tolerance). 반환된 딕셔너리는
    이후 루프 진입 전 `if target in completed_map: skip` 판단에 사용되어
    중복 API 호출과 토큰 낭비를 원천 차단합니다.
    """
    completed: dict = {}
    jsonl_path = RESULTS_JSONL_PATH_current()
    if not os.path.exists(jsonl_path):
        return completed
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(f"screening_results.jsonl 손상된 라인 스킵 (line {line_no})")
                    continue
                student_key = record.get("student")
                if student_key:
                    completed[student_key] = record
    except OSError as e:
        logger.error(f"screening_results.jsonl 로드 실패: {e}")
    return completed

def append_screening_result(result: dict):
    """피실험자 1명(Atomic Unit)의 최종 스크리닝 결과를 즉시 행 단위로 append-only 영속화합니다.

    전역 버퍼를 거치지 않고 디스크에 즉시 flush + fsync하여, 사용자가 프로세스를
    강제 종료하더라도 이미 완료된 데이터는 유실되지 않도록 보장합니다.
    """
    try:
        jsonl_path = RESULTS_JSONL_PATH_current()
        os.makedirs(os.path.dirname(jsonl_path), exist_ok=True)
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
        student = result.get("student", "?")
        msg = f"[SUCCESS: Saved Screening Result for {student} to screening_results.jsonl]"
        print(msg)
        add_log(msg)
    except OSError as e:
        logger.error(f"screening_results.jsonl 저장 실패: {e}")

# [폐기] LLM 기반 저자 역추적 lookup_author()는 완전히 제거되었다.
# 저자 확정은 utils/book_api.lookup_book_metadata() (네이버 책 검색 OpenAPI,
# .env의 NAVER_CLIENT_ID/SECRET 사용)가 Zero-Token으로 대체 수행한다.
def resolve_author_via_naver(book_title: str) -> str:
    """네이버 책 검색 API로 도서의 공식 저자명을 확정한다 (LLM 호출·토큰 소모 0).

    실패(키 미설정/미검색/통신 오류) 시 'Unknown'을 반환하며 파이프라인은 계속 진행된다.
    """
    meta = lookup_book_metadata(book_title)
    if meta and meta.get("author"):
        return meta["author"]
    return "Unknown"

def ensure_book_factsheet_cached(
    book_title: str,
    author: str,
    provider_verify,
    book_cache: dict,
    factsheets_dir: str,
    no_web: bool,
) -> str:
    """도서 1권의 팩트시트를 확보한다 (CASE A: Cache Hit 재사용 / CASE B: Cache Miss → JIT 생성 후 Write-Through).

    - Cache Hit: book_cache.json의 로컬 팩트시트를 즉시 반환 (LLM 호출·토큰 소모 0).
    - Cache Miss: '그 시점에 해당 도서 1권에 대해서만' LLM을 호출해 생성하고 즉시
      book_cache.json에 Append(Write-Through: flush+fsync)한다. 생성 중에는
      analysis_state["factsheet_generating"]에 도서명을 세팅하여 UI가
      "'{도서명}' 팩트시트 신규 생성 중..." 스피너를 표시하도록 한다.
    Phase 1.5(마이크로 배치 선제 생성)와 Phase 2(JIT 검증)에서 공통으로 재사용된다.
    """
    cache_key = normalize_cache_key(book_title, author)

    with book_cache_lock:
        cached_entry = book_cache.get(cache_key)

    if cached_entry is not None:
        add_log(f"💾 캐시 히트! '{cache_key}' 도서 정보를 book_cache.json에서 불러옵니다. (토큰 0)")
        factsheet_content = cached_entry.get("factsheet", "")
    else:
        if no_web:
            add_log(f"🌐 캐시 미스했으나 no_web 옵션 활성화 상태로 생략: {cache_key}")
            return ""

        # Cache Miss: 해당 도서 1권만 JIT 생성. UI 스피너 플래그를 세팅해
        # 사용자에게 시스템이 다운된 것이 아님을 인지시킨다 (finally에서 반드시 해제).
        with state_lock:
            analysis_state["factsheet_generating"] = book_title
        add_log(f"🌐 캐시 미스! '{book_title}' 팩트시트 신규 생성 중... (해당 1권만 LLM 호출)")
        try:
            factsheet_content = provider_verify.generate_factsheet(book_title)
        finally:
            with state_lock:
                analysis_state["factsheet_generating"] = None

        with book_cache_lock:
            book_cache[cache_key] = {
                "book_title": book_title,
                "author": author,
                "factsheet": factsheet_content,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_book_cache(book_cache)
        add_log(f"💾 '{cache_key}' 도서 정보를 book_cache.json에 저장 완료 (즉시 Append).")

    if factsheet_content:
        normalized_title = _normalize_title(book_title)
        if normalized_title:
            os.makedirs(factsheets_dir, exist_ok=True)
            filepath = os.path.join(factsheets_dir, f"{normalized_title}.md")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(factsheet_content)
                f.flush()
                os.fsync(f.fileno())
            success_msg = f"[SUCCESS: Saved Fact Sheet for {book_title} to local file]"
            print(success_msg)
            add_log(success_msg)

    return factsheet_content

# -------------------------------------------------------------
# 모델 캐시 로드, 저장 및 백그라운드 갱신 헬퍼 함수
# -------------------------------------------------------------
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models_cache.json")
models_cache_data = None

def load_models_cache() -> dict:
    """models_cache.json에서 캐싱된 모델 목록을 로드합니다. (메모리 캐싱 활용)"""
    global models_cache_data
    if models_cache_data is not None:
        return models_cache_data
    if not os.path.exists(CACHE_FILE):
        models_cache_data = {}
        return models_cache_data
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            models_cache_data = json.load(f) or {}
            return models_cache_data
    except Exception as e:
        logger.error(f"모델 캐시 로드 실패: {e}")
        models_cache_data = {}
        return models_cache_data

def save_models_cache(cache_data: dict):
    """models_cache.json에 모델 캐시를 저장합니다. 기존 캐시와 병합합니다."""
    global models_cache_data
    try:
        existing = load_models_cache()
        existing.update(cache_data)
        models_cache_data = existing
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"모델 캐시 저장 실패: {e}")

def update_provider_models_sync(provider: str, api_key: str) -> tuple[bool, Optional[str]]:
    """특정 프로바이더의 모델 목록을 동기적으로 조회하여 캐시에 저장합니다.
    
    Returns:
        (성공 여부, 에러 메시지)
    """
    try:
        if not api_key:
            return False, "API 키가 제공되지 않았습니다."
        
        # 마스킹되어 있어도 유효하면 스킵하지 않고 조회 시도
        if api_key.startswith("•••") or "마스킹" in api_key:
            return False, "유효하지 않거나 마스킹된 API 키입니다."
            
        models = []
        if provider == "gemini":
            from providers.gemini_provider import GeminiProvider
            models = GeminiProvider.list_available_models(api_key)
        elif provider == "anthropic":
            from providers.anthropic_provider import AnthropicProvider
            models = AnthropicProvider.list_available_models(api_key)
        elif provider == "openai":
            from providers.openai_provider import OpenAIProvider
            models = OpenAIProvider.list_available_models(api_key)
        else:
            return False, f"지원하지 않는 프로바이더: {provider}"
        
        if models:
            save_models_cache({provider: models})
            logger.info(f"[{provider.upper()}] 모델 목록 동적 갱신 성공: {len(models)}개 모델 로드됨.")
            return True, None
        else:
            return False, f"{provider.upper()} API로부터 모델 목록을 가져오지 못했습니다. (0개 모델)"
    except Exception as e:
        err_msg = str(e)
        logger.error(f"[{provider.upper()}] 모델 목록 갱신 중 에러 발생: {err_msg}")
        return False, err_msg

def update_provider_models_worker(provider: str, api_key: str):
    """특정 프로바이더의 모델 목록을 조회하여 캐시에 저장하는 백그라운드 워커."""
    update_provider_models_sync(provider, api_key)

def trigger_bg_model_refresh(api_keys: dict):
    """전체 프로바이더의 백그라운드 모델 목록 갱신을 트리거합니다."""
    for provider, api_key in api_keys.items():
        if api_key and not api_key.startswith("•••") and "마스킹" not in api_key:
            t = threading.Thread(target=update_provider_models_worker, args=(provider, api_key), daemon=True)
            t.start()

def trigger_bg_refresh_for_current_user():
    """현재 로그인된 프로필의 API 키를 사용하여 백그라운드 갱신을 실행합니다."""
    session = global_user_manager.get_session_data()
    if session and session.get("api_keys"):
        trigger_bg_model_refresh(session["api_keys"])

def trigger_bg_refresh_all_profiles():
    """모든 프로필을 검사하여 찾은 API 키들로 초기 백그라운드 갱신을 시도합니다."""
    try:
        profiles = global_user_manager._data.get("profiles", {})
        merged_keys = {}
        for p_name, p_data in profiles.items():
            keys = p_data.get("api_keys", {})
            for provider, key in keys.items():
                if provider not in merged_keys and key:
                    merged_keys[provider] = key
        if merged_keys:
            trigger_bg_model_refresh(merged_keys)
    except Exception as e:
        logger.error(f"전체 프로필 키 수집 및 백그라운드 갱신 실패: {e}")

# -------------------------------------------------------------
# 공통 설정 로드 함수
# -------------------------------------------------------------
def load_config() -> dict:
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    import yaml
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

# -------------------------------------------------------------
# -------------------------------------------------------------
# 프로필 API
# -------------------------------------------------------------
@app.get("/api/profiles")
def list_profiles():
    return global_user_manager.list_profiles()

@app.get("/api/profiles/current")
def get_current_profile():
    curr = global_user_manager.get_current_profile()
    if not curr:
        return {"logged_in": False, "profile_name": None}
    
    # 세션 데이터 확인
    session = global_user_manager.get_session_data()
    if not session:
        return {"logged_in": False, "profile_name": curr}
        
    return {
        "logged_in": True,
        "profile_name": curr,
        "api_keys": list(session["api_keys"].keys()),
        "default_models": session["default_models"]
    }

@app.post("/api/profiles")
def create_profile(req: ProfileCreateRequest):
    success = global_user_manager.add_profile(name=req.name)
    if not success:
        raise HTTPException(status_code=400, detail="프로필 생성 실패 (이름 중복 등)")
    return {"message": f"프로필 '{req.name}' 생성 완료"}

@app.post("/api/profiles/login")
def login(req: LoginRequest):
    res = global_user_manager.login(req.name)
    if not res:
        raise HTTPException(status_code=401, detail="없는 프로필입니다.")
    # 로그인 성공 시 API 키가 있을 경우 백그라운드 모델 갱신 실행
    trigger_bg_refresh_for_current_user()
    return {"message": "로그인 성공", "profile": res}

@app.post("/api/profiles/logout")
def logout():
    global_user_manager.logout()
    return {"message": "로그아웃 완료"}

@app.delete("/api/profiles/{name}")
def delete_profile(name: str):
    if global_user_manager.delete_profile(name):
        return {"message": "삭제 완료"}
    raise HTTPException(status_code=404, detail="프로필을 찾을 수 없음")

@app.post("/api/profiles/keys")
def register_api_key(req: ApiKeyRegisterRequest):
    current = global_user_manager.get_current_profile()
    if not current:
        raise HTTPException(status_code=401, detail="로그인되어 있지 않습니다.")
        
    success = global_user_manager.add_api_key(
        profile_name=current,
        provider=req.provider,
        api_key=req.api_key
    )
    if success:
        trigger_bg_refresh_for_current_user()
        return {"message": f"{req.provider} API 키 등록 완료"}
    raise HTTPException(status_code=400, detail="API 키 등록 실패")

@app.post("/api/profiles/keys/batch")
def register_api_keys_batch(req: ApiKeyBatchRequest):
    current = global_user_manager.get_current_profile()
    if not current:
        raise HTTPException(status_code=401, detail="로그인되어 있지 않습니다.")
        
    # 각 공급자별로 넘어온 키가 있고, 마스킹(••••)이 아니며, 비어있지 않은 경우에만 등록
    updated = []
    
    # 헬퍼 함수
    def isValidKey(val: Optional[str]) -> bool:
        if not val:
            return False
        val_s = val.strip()
        if not val_s or val_s.startswith("•••") or "마스킹" in val_s:
            return False
        return True

    if isValidKey(req.gemini):
        global_user_manager.add_api_key(current, "gemini", req.gemini.strip())
        updated.append("gemini")
        
    if isValidKey(req.anthropic):
        global_user_manager.add_api_key(current, "anthropic", req.anthropic.strip())
        updated.append("anthropic")
        
    if isValidKey(req.openai):
        global_user_manager.add_api_key(current, "openai", req.openai.strip())
        updated.append("openai")
        
    if updated:
        trigger_bg_refresh_for_current_user()
        
    return {"message": f"API 키 일괄 업데이트 완료: {', '.join(updated) if updated else '변경 없음'}"}

@app.delete("/api/profiles/keys/{provider}")
def delete_api_key(provider: str):
    current = global_user_manager.get_current_profile()
    if not current:
        raise HTTPException(status_code=401, detail="로그인되어 있지 않습니다.")
    
    if global_user_manager.delete_api_key(current, provider):
        return {"message": f"{provider} API 키 삭제 완료"}
    raise HTTPException(status_code=404, detail="등록된 키를 찾을 수 없음")

@app.post("/api/profiles/select-model")
def select_model(req: ModelSelectRequest):
    current = global_user_manager.get_current_profile()
    if not current:
        raise HTTPException(status_code=401, detail="로그인되어 있지 않습니다.")
    
    success = global_user_manager.select_model(
        profile_name=current,
        screening_provider=req.screening_provider,
        screening_model=req.screening_model,
        verify_provider=req.verify_provider,
        verify_model=req.verify_model
    )
    if success:
        return {"message": "기본 모델 설정 변경 완료"}
    raise HTTPException(status_code=400, detail="모델 설정 변경 실패")

# -------------------------------------------------------------
# 설정 API
# -------------------------------------------------------------
@app.get("/api/config")
def get_config():
    config = load_config()
    fallback = config.get("fallback_models", {})
    cache = load_models_cache()
    
    # 1차 Fallback (models_cache.json), 2차 Fallback (config.yaml fallback_models) 병합
    available = {}
    for provider in ["gemini", "anthropic", "openai"]:
        if provider in cache and cache[provider]:
            available[provider] = cache[provider]
        else:
            available[provider] = fallback.get(provider, [])
            
    return {
        "available_models": available,
        "rules": config.get("rules", {})
    }

@app.post("/api/config/refresh")
def refresh_config(req: Optional[RefreshConfigRequest] = None):
    session = global_user_manager.get_session_data()
    if not session or not session.get("api_keys"):
        raise HTTPException(status_code=401, detail="먼저 로그인하고 API 키를 등록해야 모델 목록을 갱신할 수 있습니다.")
        
    api_keys = session["api_keys"]
    target_provider = req.provider if req else None
    
    success_providers = []
    failed_providers = {}
    
    providers_to_refresh = [target_provider] if target_provider else ["gemini", "anthropic", "openai"]
    
    for provider in providers_to_refresh:
        api_key = api_keys.get(provider)
        if not api_key:
            if target_provider:
                raise HTTPException(status_code=400, detail=f"{provider} API 키가 등록되어 있지 않습니다.")
            continue
            
        success, error_detail = update_provider_models_sync(provider, api_key)
        if success:
            success_providers.append(provider)
        else:
            failed_providers[provider] = error_detail
            
    if not success_providers and not failed_providers:
        raise HTTPException(status_code=400, detail="등록된 API 키가 없어 갱신을 진행할 수 없습니다.")
        
    msg_parts = []
    if success_providers:
        msg_parts.append(f"성공: {', '.join(success_providers).upper()}")
    if failed_providers:
        failed_details = ", ".join(f"{k.upper()}({v})" for k, v in failed_providers.items())
        msg_parts.append(f"실패: {failed_details}")
        
    message = "모델 목록 갱신 결과 - " + " | ".join(msg_parts)
    
    if not success_providers:
        raise HTTPException(status_code=400, detail=message)
        
    return {
        "success": success_providers,
        "failed": failed_providers,
        "message": message
    }

# -------------------------------------------------------------
# 네이티브 폴더 선택 다이얼로그 API
# -------------------------------------------------------------
@app.get("/api/pick-folder")
def pick_folder(initial: str = ""):
    """서브프로세스에서 tkinter를 사용해 네이티브 OS 폴더 선택 창을 열고 선택된 경로를 반환합니다."""
    import subprocess
    import sys
    
    script = f"""
import tkinter as tk
from tkinter import filedialog
import os

root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)

initial = {repr(initial)}
start_dir = initial if initial and os.path.isdir(initial) else os.path.expanduser("~")

selected = filedialog.askdirectory(
    title="제출물 폴더를 선택하세요",
    initialdir=start_dir,
    mustexist=True
)
if selected:
    print(selected.replace("/", "\\\\"), end="")
"""
    try:
        encoding_type = "cp949" if sys.platform == "win32" else "utf-8"
        res = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            encoding=encoding_type,
            errors="ignore",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        if res.returncode != 0:
            err_msg = res.stderr.strip() if res.stderr else f"Exit code: {res.returncode}"
            logger.error(f"폴더 선택 서브프로세스 실패: {err_msg}")
            raise HTTPException(status_code=500, detail=f"폴더 선택 탐색기 실행 실패: {err_msg}")
            
        path = res.stdout.strip() if res.stdout else None
        return {"path": path}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"폴더 선택 에러: {e}")
        raise HTTPException(status_code=500, detail=f"폴더 선택 에러: {e}")


@app.get("/api/pick-file")
def pick_file(initial: str = ""):
    """서브프로세스에서 tkinter를 사용해 네이티브 OS 파일 선택 창을 열고 선택된 다중 경로를 반환합니다."""
    import subprocess
    import sys
    
    script = f"""
import tkinter as tk
from tkinter import filedialog
import os

root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)

initial = {repr(initial)}
if initial:
    # 다중 경로 구분자인 세미콜론이 있으면 첫 번째 파일 경로 기준으로 폴더 결정
    first_path = initial.split(";")[0].strip()
    if os.path.isdir(first_path):
        start_dir = first_path
    elif os.path.isfile(first_path):
        start_dir = os.path.dirname(first_path)
    else:
        start_dir = os.path.expanduser("~")
else:
    start_dir = os.path.expanduser("~")

selected = filedialog.askopenfilenames(
    title="제출물 파일들을 선택하세요",
    initialdir=start_dir,
    filetypes=[
        ("모든 지원 파일", "*.txt *.docx *.pdf *.xlsx *.xls *.csv"),
        ("텍스트 파일 (*.txt)", "*.txt"),
        ("Word 문서 (*.docx)", "*.docx"),
        ("PDF 문서 (*.pdf)", "*.pdf"),
        ("Excel 통합 문서 (*.xlsx *.xls)", "*.xlsx *.xls"),
        ("CSV 파일 (*.csv)", "*.csv"),
        ("모든 파일 (*.*)", "*.*")
    ]
)
if selected:
    paths = ";".join(selected)
    print(paths.replace("/", "\\\\"), end="")
"""
    try:
        encoding_type = "cp949" if sys.platform == "win32" else "utf-8"
        res = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            encoding=encoding_type,
            errors="ignore",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        if res.returncode != 0:
            err_msg = res.stderr.strip() if res.stderr else f"Exit code: {res.returncode}"
            logger.error(f"파일 선택 서브프로세스 실패: {err_msg}")
            raise HTTPException(status_code=500, detail=f"파일 선택 탐색기 실행 실패: {err_msg}")
            
        path = res.stdout.strip() if res.stdout else None
        return {"path": path}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"파일 선택 에러: {e}")
        raise HTTPException(status_code=500, detail=f"파일 선택 에러: {e}")


# -------------------------------------------------------------
# 다중 프로젝트(Workspace) 관리 API
# 저장 구조: data/projects/{profile_name}/{project_id}/session.json
# -------------------------------------------------------------
class ProjectCreateRequest(BaseModel):
    name: Optional[str] = None

def _require_login_profile() -> str:
    current = global_user_manager.get_current_profile()
    if not current:
        raise HTTPException(status_code=401, detail="먼저 로그인해야 프로젝트를 관리할 수 있습니다.")
    return current

def _require_active_project() -> dict:
    """데이터 조작/분석 전 활성 프로젝트 존재를 강제하는 Guard Clause."""
    active = get_active_project()
    if not active:
        raise HTTPException(
            status_code=400,
            detail="활성 프로젝트가 없습니다. [프로젝트 대시보드]에서 프로젝트를 선택(이어하기)하거나 새로 생성해 주세요.",
        )
    return active

@app.get("/api/projects")
def api_list_projects():
    """현재 로그인 프로필의 프로젝트 목록(요약 정보 포함)을 반환한다.

    구버전 단일 session_progress.json이 남아있으면 최초 1회 프로젝트로 자동 이관한다.
    """
    profile = _require_login_profile()
    migrated = migrate_legacy_session(profile)
    active = get_active_project()
    return {
        "projects": list_projects(profile),
        "active_project_id": active["project_id"] if active and active.get("profile") == profile else None,
        "migrated": migrated,
    }

@app.post("/api/projects")
def api_create_project(req: ProjectCreateRequest):
    """새 프로젝트 생성 (초기화된 빈 세션 파일 기록). 활성화는 별도 activate 호출."""
    profile = _require_login_profile()
    name = (req.name or "").strip() or time.strftime("검토 프로젝트 %Y-%m-%d %H:%M")
    try:
        meta = create_project(profile, name)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"프로젝트 생성 실패: {e}")
    return {"message": f"프로젝트 '{name}' 생성 완료", "project": meta}

@app.post("/api/projects/{project_id}/activate")
def api_activate_project(project_id: str):
    """프로젝트를 '현재 활성 프로젝트'로 지정하고 세션 데이터를 메모리로 로드한다."""
    profile = _require_login_profile()
    with state_lock:
        if _pipeline_busy():
            raise HTTPException(status_code=400, detail="분석이 진행 중일 때는 프로젝트를 전환할 수 없습니다. 먼저 정지해 주세요.")

    data = load_session_progress(profile, project_id)
    if data is None:
        raise HTTPException(status_code=404, detail="프로젝트 세션 파일을 찾을 수 없거나 손상되었습니다.")

    meta = data.get("project") or {}
    set_active_project(profile, project_id, name=meta.get("name") or project_id,
                       created_at=meta.get("created_at") or "")

    results = data.get("results", [])
    # 학번 '.0' 꼬리표 마이그레이션 (구버전 데이터 호환)
    migrated_count = sum(1 for r in results if sanitize_student_identity(r))

    with state_lock:
        analysis_state["results"] = results
        analysis_state["cost_summary"] = data.get("cost_summary", {})
        analysis_state["status"] = "idle"
        analysis_state["error_message"] = ""
        analysis_state["logs"] = []

    if migrated_count:
        save_session_progress(results, data.get("cost_summary"), status="migrated")

    add_log(f"📂 프로젝트 활성화: '{meta.get('name') or project_id}' — 학생 {len(results)}명 로드 (저장 시각: {data.get('saved_at', '미상')})")
    return {
        "message": f"프로젝트 '{meta.get('name') or project_id}' 활성화 완료",
        "project": {"project_id": project_id, "name": meta.get("name") or project_id},
        "total": len(results),
    }

@app.delete("/api/projects/{project_id}")
def api_delete_project(project_id: str):
    """프로젝트 폴더(세션·체크포인트 포함)를 완전히 삭제한다."""
    profile = _require_login_profile()
    active = get_active_project()
    is_active_target = bool(active and active.get("project_id") == project_id)
    with state_lock:
        if is_active_target and _pipeline_busy():
            raise HTTPException(status_code=400, detail="분석이 진행 중인 활성 프로젝트는 삭제할 수 없습니다. 먼저 정지해 주세요.")

    if not delete_project(profile, project_id):
        raise HTTPException(status_code=404, detail="해당 프로젝트를 찾을 수 없습니다.")

    # 활성 프로젝트를 삭제한 경우: 비활성화 + 메모리 데이터셋 초기화
    if is_active_target:
        clear_active_project()
        with state_lock:
            analysis_state["results"] = []
            analysis_state["cost_summary"] = {}
    return {"message": "프로젝트 삭제 완료", "deactivated": is_active_target}

# -------------------------------------------------------------
# Data Ingestion API — 파일 읽기를 파이프라인에서 완전히 분리 (DB형 메모리 상태 관리)
# -------------------------------------------------------------
class DataImportRequest(BaseModel):
    path: str

@app.post("/api/data/import")
def import_data(req: DataImportRequest):
    """[데이터 가져오기] 파일/폴더 → 메모리 데이터셋(analysis_state["results"]) 적재.

    Smart Append: 기존에 로드되어 작업 중인 레코드는 절대 덮어쓰지 않는다.
    학번(없으면 이름) 기준으로 중복 학생은 무시하고 신규 학생만 Append한 뒤
    활성 프로젝트의 session.json에 즉시 동기화한다. 이후 분석 파이프라인은
    폴더를 다시 뒤지지 않고 이 메모리 데이터셋만 순회한다.
    """
    _require_active_project()
    with state_lock:
        if _pipeline_busy():
            raise HTTPException(status_code=400, detail="분석이 진행 중일 때는 데이터를 가져올 수 없습니다. 먼저 정지해 주세요.")

    path = (req.path or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="가져올 파일 또는 폴더 경로를 지정해 주세요.")

    submissions = read_submissions(path)
    if not submissions:
        raise HTTPException(status_code=404, detail="지원되는 제출물을 찾지 못했습니다. (지원 형식: Excel, CSV, PDF, TXT, DOCX)")

    # 메타데이터(docx)는 가져오기 시점에 1회만 추출 — 파이프라인은 파일을 다시 읽지 않는다.
    for sub in submissions:
        sanitize_student_identity(sub)
        sub["filename"] = sub["student"]
        if sub.get("file_type") == "docx":
            try:
                sub["metadata"] = extract_docx_metadata(sub["file_path"])
            except Exception as e:
                logger.warning(f"docx 메타데이터 추출 실패({sub.get('file_path')}): {e}")
                sub["metadata"] = None
        else:
            sub["metadata"] = None

    with state_lock:
        existing_keys = {student_dedupe_key(r) for r in analysis_state["results"]}
        added = []
        skipped = 0
        for sub in submissions:
            key = student_dedupe_key(sub)
            if key in existing_keys:
                skipped += 1
                continue
            existing_keys.add(key)
            added.append(sub)
        analysis_state["results"].extend(added)
        snapshot = list(analysis_state["results"])

    # [Data Sanitization — Zero-Token] 데이터 로드 시점에 도서 메타데이터를 확정한다.
    # 1) '도서명(저자명)' 복합 텍스트를 즉시 분리하고,
    # 2) 저자가 여전히 없는 도서는 네이버 책 검색 API(.env 키)로 공식 저자를 조회한다.
    # added의 각 원소는 analysis_state["results"] 내 동일 dict 객체이므로 스냅샷 저장에 그대로 반영된다.
    naver_author_memo: dict[str, str] = {}
    naver_resolved = 0
    for sub in added:
        parsed_title, parsed_author = parse_book_title_author(sub.get("book_title"))
        if parsed_title:
            sub["book_title"] = parsed_title
        if parsed_author and not sub.get("author"):
            sub["author"] = parsed_author
        title = sub.get("book_title")
        if title and not sub.get("author"):
            if title not in naver_author_memo:
                meta = lookup_book_metadata(title)
                naver_author_memo[title] = (meta or {}).get("author", "")
            if naver_author_memo[title]:
                sub["author"] = naver_author_memo[title]
                naver_resolved += 1

    save_session_progress(snapshot, status="loaded")
    msg = f"데이터 가져오기 완료: 신규 {len(added)}명 추가, 중복 {skipped}명 무시 (총 {len(snapshot)}명 적재)"
    if naver_resolved:
        msg += f" / 네이버 책 검색으로 저자 확정 {naver_resolved}건 (토큰 0)"
    add_log(f"📥 [Smart Append] {msg} — session_progress.json 동기화 완료.")
    return {"message": msg, "added": len(added), "skipped": skipped, "total": len(snapshot)}

# -------------------------------------------------------------
# 학생 레코드 수동 CRUD API (메모리 상태 + 세션 파일 즉시 영속화)
# -------------------------------------------------------------
class StudentCreateRequest(BaseModel):
    student_id: str = ""
    student_name: str
    book_title: str = ""
    text: str

class StudentUpdateRequest(BaseModel):
    student_id: Optional[str] = None
    student_name: Optional[str] = None
    book_title: Optional[str] = None
    text: Optional[str] = None

def _build_student_key(student_id: str, student_name: str) -> str:
    """'학번_이름' 복합키를 구성한다 (file_reader의 키 규칙과 동일)."""
    if student_id and student_name:
        return f"{student_id}_{student_name}"
    return student_id or student_name

def _persist_results_snapshot():
    """state_lock 밖에서 호출: 현재 메모리 데이터셋을 session_progress.json에 저장."""
    with state_lock:
        snapshot = list(analysis_state["results"])
    save_session_progress(snapshot, status="edited")
    return len(snapshot)

@app.post("/api/students")
def create_student(req: StudentCreateRequest):
    """[학생 수동 추가] 파일 없이 텍스트 복붙으로 학생 1명을 메모리 데이터셋에 추가한다."""
    _require_active_project()
    student_id = strip_float_tail(req.student_id or "")
    student_name = (req.student_name or "").strip()
    text = (req.text or "").strip()
    if not student_name:
        raise HTTPException(status_code=400, detail="이름은 필수 입력입니다.")
    if not text:
        raise HTTPException(status_code=400, detail="독후감 본문은 필수 입력입니다.")

    record = {
        "student": _build_student_key(student_id, student_name),
        "student_id": student_id,
        "student_name": student_name,
        "book_title": (req.book_title or "").strip() or None,
        "text": text,
        "file_path": "",
        "file_type": "manual",
        "filename": _build_student_key(student_id, student_name),
        "metadata": None,
    }

    with state_lock:
        if _pipeline_busy():
            raise HTTPException(status_code=400, detail="분석이 진행 중일 때는 학생을 추가할 수 없습니다.")
        existing_keys = {student_dedupe_key(r) for r in analysis_state["results"]}
        if student_dedupe_key(record) in existing_keys:
            raise HTTPException(status_code=409, detail=f"이미 등록된 학생입니다: {record['student']}")
        analysis_state["results"].append(record)

    total = _persist_results_snapshot()
    add_log(f"➕ [수동 추가] 학생 '{record['student']}' 등록 완료 (총 {total}명) — 세션 파일 동기화.")
    return {"message": f"학생 '{record['student']}' 추가 완료", "student": record["student"], "total": total}

@app.put("/api/students/{student_key}")
def update_student(student_key: str, req: StudentUpdateRequest):
    """[수정] 학생 레코드의 학번/이름/도서명/본문을 갱신한다 (student_key = '학번_이름' 복합키)."""
    _require_active_project()
    with state_lock:
        if _pipeline_busy():
            raise HTTPException(status_code=400, detail="분석이 진행 중일 때는 학생 정보를 수정할 수 없습니다.")
        record = next((r for r in analysis_state["results"] if str(r.get("student")) == student_key), None)
        if record is None:
            raise HTTPException(status_code=404, detail=f"해당 학생을 찾을 수 없습니다: {student_key}")

        # 1) 변경 후보값을 먼저 계산하고 키 충돌을 검증한 뒤, 2) 통과 시에만 일괄 적용한다
        #    (충돌 시 레코드가 부분적으로만 변경되는 것을 방지 — Atomic Update).
        new_id = strip_float_tail(req.student_id) if req.student_id is not None else record.get("student_id", "")
        new_name = (req.student_name.strip() if req.student_name is not None and req.student_name.strip()
                    else record.get("student_name", ""))
        new_key = _build_student_key(new_id, new_name)
        if new_key and new_key != student_key:
            if any(str(r.get("student")) == new_key for r in analysis_state["results"] if r is not record):
                raise HTTPException(status_code=409, detail=f"동일 키의 학생이 이미 존재합니다: {new_key}")

        record["student_id"] = new_id
        record["student_name"] = new_name
        if req.book_title is not None:
            record["book_title"] = req.book_title.strip() or None
        if req.text is not None and req.text.strip():
            record["text"] = req.text.strip()
        if new_key and new_key != student_key:
            record["student"] = new_key
            record["filename"] = new_key

    total = _persist_results_snapshot()
    add_log(f"✏️ [수정] 학생 '{student_key}' → '{record['student']}' 정보 갱신 완료 — 세션 파일 동기화.")
    return {"message": f"학생 '{record['student']}' 수정 완료", "student": record["student"], "total": total}

@app.delete("/api/students/{student_key}")
def delete_student(student_key: str):
    """[삭제] 학생 레코드를 메모리 데이터셋과 활성 프로젝트 세션 파일에서 제거한다."""
    _require_active_project()
    with state_lock:
        if _pipeline_busy():
            raise HTTPException(status_code=400, detail="분석이 진행 중일 때는 학생을 삭제할 수 없습니다.")
        before = len(analysis_state["results"])
        analysis_state["results"] = [
            r for r in analysis_state["results"] if str(r.get("student")) != student_key
        ]
        removed = before - len(analysis_state["results"])
        if removed == 0:
            raise HTTPException(status_code=404, detail=f"해당 학생을 찾을 수 없습니다: {student_key}")

    total = _persist_results_snapshot()
    add_log(f"🗑️ [삭제] 학생 '{student_key}' 제거 완료 (총 {total}명) — 세션 파일 동기화.")
    return {"message": f"학생 '{student_key}' 삭제 완료", "total": total}

# -------------------------------------------------------------
# 분석 API & 백그라운드 태스크
# -------------------------------------------------------------
def run_pipeline_thread(req: AnalyzeRequest, session_data: dict, config: dict):
    global analysis_state
    
    try:
        update_progress(5, "메모리 데이터셋 로드 중...")

        # API 키 검증
        api_keys = session_data.get("api_keys", {})
        screening_key = api_keys.get(req.screening_provider)
        verify_key = api_keys.get(req.verify_provider)

        if not screening_key:
            raise Exception(f"2단계 스크리닝을 위한 {req.screening_provider} API Key가 등록되지 않았습니다.")
        if not req.no_verify and not verify_key:
            raise Exception(f"3단계 사실 검증을 위한 {req.verify_provider} API Key가 등록되지 않았습니다.")

        # [Data Ingestion 분리] 파이프라인은 더 이상 폴더/파일을 직접 읽지 않는다.
        # [데이터 가져오기](POST /api/data/import)·[학생 수동 추가](POST /api/students)로
        # 적재된 analysis_state["results"] 인메모리 데이터셋만을 대상으로 순회(Iterate)한다.
        # 아래 submissions의 각 원소는 analysis_state["results"]와 '동일한 dict 객체'이므로
        # 이후 단계별 in-place 갱신이 별도 재대입 없이 UI(/api/results)에 즉시 반영된다.
        with state_lock:
            submissions = list(analysis_state["results"])
        if not submissions:
            raise Exception("적재된 학생 데이터가 없습니다. 먼저 [데이터 가져오기] 또는 [학생 수동 추가]로 학생을 등록해 주세요.")

        add_log(f"✅ 메모리 데이터셋 {len(submissions)}명 로드 완료 (파일 재스캔 없음).")

        # 메타데이터 보충: 가져오기 시점에 이미 추출되어 있으므로, 구버전 세션 복원 등
        # 메타데이터 필드가 없는 레코드에 한해서만 1회 보충한다.
        update_progress(15, "메타데이터 확인 중...")
        for sub in submissions:
            sub["filename"] = sub.get("filename") or sub["student"]
            if "metadata" not in sub:
                if sub.get("file_type") == "docx" and sub.get("file_path") and os.path.exists(sub["file_path"]):
                    try:
                        sub["metadata"] = extract_docx_metadata(sub["file_path"])
                    except Exception as e:
                        logger.warning(f"docx 메타데이터 보충 실패({sub.get('file_path')}): {e}")
                        sub["metadata"] = None
                else:
                    sub["metadata"] = None

        # CostTracker 설정
        cost_tracker = CostTracker(config)

        # [토큰 최적화 대안 — 구조적 제안]
        # 1) Anthropic Prompt Caching: 동일 도서를 읽은 학생 N명 연속 검증 시 팩트시트를
        #    system 블록 cache_control로 지정하면 2번째 호출부터 입력 토큰이 캐시 단가(≈1/10)로 과금.
        # 2) 로컬 임베딩(SentenceTransformers) 1차 유사도 필터링: 학생 글 ↔ 팩트시트 문단 간
        #    코사인 유사도로 무관한 주장을 사전 제거하면 3단계 verify 입력 토큰 추가 절감.
        add_log("💡 [최적화 제안] 동일 도서 반복 검증에는 Prompt Caching, 검증 전 로컬 임베딩(SentenceTransformers) 1차 필터링을 적용하면 토큰을 추가 절감할 수 있습니다.")

        # -----------------------------------------------------------------
        # 체크포인트-재개(Resume) 로직: screening_results.jsonl 스캔 → 완료 인덱스 로드
        # 매 루프 진입 전 [학번_성명]이 완료 인덱스에 있으면 전체 파이프라인을 스킵하여
        # 중복 API 호출 및 토큰 낭비를 원천 차단한다 (Token Waste Zero).
        # -----------------------------------------------------------------
        update_progress(20, "체크포인트 스캔 중 (이전 실행 결과 확인)...")
        completed_map = load_completed_results()

        resumed_results = []
        submissions_to_process = []
        for sub in submissions:
            if sub["student"] in completed_map:
                # 체크포인트 데이터를 '메모리 레코드 자체'에 병합한다 (동일 dict 객체 유지).
                # 리스트를 재대입하지 않으므로 미처리 학생도 UI 목록에서 사라지지 않는다.
                checkpoint = completed_map[sub["student"]]
                for k, v in checkpoint.items():
                    if k == "text" and not v and sub.get("text"):
                        continue  # CSV 백필 등 본문이 비어있는 체크포인트가 원본 본문을 지우지 않도록 보호
                    sub[k] = v
                resumed_results.append(sub)
            else:
                submissions_to_process.append(sub)

        if resumed_results:
            add_log(f"🔁 체크포인트 발견: {len(resumed_results)}명은 이전에 이미 완료되어 스킵합니다 (중복 API 호출/토큰 소모 0).")
        add_log(f"▶️ 신규 처리 대상: {len(submissions_to_process)}명")

        new_results: list = []

        def _finalize_and_persist_student(r: dict):
            """피실험자 1명(Atomic Unit)의 처리가 최종 완료되는 즉시 로컬 파일에
            append-only로 영속화한다. 레코드는 analysis_state["results"] 내 동일 객체이므로
            UI에는 이미 실시간 반영된 상태이며, 세션 스냅샷(session_progress.json)도 함께
            갱신하여 서버가 언제 재기동되더라도 이어서 작업할 수 있다."""
            append_screening_result(r)
            with state_lock:
                snapshot = list(analysis_state["results"])
            save_session_progress(snapshot, status="running")

        if not submissions_to_process:
            add_log("✅ 모든 대상이 체크포인트에 이미 존재하여 신규 스크리닝을 생략합니다.")
        else:
            # 1단계 규칙 기반 검사 (신규 대상만)
            update_progress(25, "1단계: 규칙 기반 검사 중...")
            for i, sub in enumerate(submissions_to_process, 1):
                check_control_state("1단계", i, len(submissions_to_process), sub["student"])
                add_log(f"[1단계] ({i}/{len(submissions_to_process)}) {sub['student']} 검사 중...")
                stage1_res = run_stage1(sub.get("text", ""), sub.get("metadata"), sub["filename"], config)
                # '도서명(저자명)' 복합 텍스트 파싱: 도서명 필드에 후미 괄호로 저자명이
                # 붙어 들어온 경우, 여기서 즉시 분리하여 저자 정보 유실을 방지한다.
                parsed_book_title, parsed_author = parse_book_title_author(sub.get("book_title"))
                # 메모리 레코드(동일 dict 객체)를 in-place 갱신 → 재대입 없이 UI 즉시 반영
                sub.update({
                    "student_name": sub.get("student_name") or sub["student"],
                    "book_title": parsed_book_title,
                    "author": parsed_author or sub.get("author") or "",
                    "rule_score": stage1_res["rule_score"],
                    # 1단계 위험도 등급 (Safe/Warning/Danger) — UI 배지 시각화용
                    "risk_grade": stage1_res.get("risk_grade", ""),
                    "rule_details": stage1_res["details"],
                })
                new_results.append(sub)

            # book_cache / factsheets_dir / book_author_map은 Phase 1.5 마이크로 배치 선제
            # 생성 스레드와 3단계 JIT 팩트시트 확보 로직이 공유하는 상태이므로 한 번만 초기화한다.
            factsheets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "factsheets")
            os.makedirs(factsheets_dir, exist_ok=True)
            book_cache = load_book_cache()
            book_author_map: dict[str, str] = {}

            def _resolve_author(book_title: str) -> str:
                """도서 저자 확보 (우선순위: 세션 메모 → 레코드 저장값('도서명(저자)' 파싱
                또는 데이터 가져오기 시 네이버 확정값) → book_cache 도서명 일치 폴백
                → 최후에 네이버 책 검색 API — 전 경로 LLM 호출 없음, Zero-Token).
                Phase 1.5 선제 생성과 Phase 2 JIT 생성이 공통으로 사용한다."""
                if book_title in book_author_map:
                    return book_author_map[book_title]
                author = next(
                    (r.get("author") for r in new_results
                     if r.get("book_title") == book_title and r.get("author")),
                    None,
                )
                if not author:
                    # Title-first 캐시 폴백: 저자 미상이라도 도서명 정규화 일치로 기존
                    # 캐시 엔트리를 먼저 탐색 → 캐시 히트 시 외부 API 호출조차 생략.
                    with book_cache_lock:
                        cached_hit = find_cached_book_entry_by_title(book_title, book_cache)
                    if cached_hit:
                        author = cached_hit[1].get("author") or "Unknown"
                        add_log(f"💾 캐시 재사용: '{book_title}' 저자('{author}') 복원 (토큰 0)")
                    else:
                        add_log(f"🔍 '{book_title}' 저자 정보 누락 — 네이버 책 검색 API로 확정 중... (Zero-Token)")
                        author = resolve_author_via_naver(book_title)
                        if author != "Unknown":
                            add_log(f"✅ 네이버 API 저자 확정: '{book_title}' → '{author}' (LLM 호출·토큰 소모 0)")
                        else:
                            add_log(f"⚠️ 네이버 API에서 '{book_title}' 저자를 찾지 못해 'Unknown'으로 진행합니다.")
                book_author_map[book_title] = author
                return author

            # [Zero-Prefetch] 사전 생성(Phase 1.5) 로직은 완전히 제거되었다.
            # 모든 팩트시트는 3단계 검증 중 해당 도서가 등장하는 시점에만
            # Cache Hit/Miss 판정을 거쳐 1권 단위 JIT로 확보된다.

            # Step A 정지선(Breakpoint): 1단계(토큰 비소비, 규칙 기반)가 전수 완료되어
            # 결과 리스트가 전부 렌더링된 뒤 명시적으로 정지한다. 사용자가 [다음 단계 진행]
            # 버튼을 클릭(POST /api/analyze/next-phase)하기 전까지 이 지점을 절대 통과하지
            # 않으므로, 즉시 다음 단계로 넘어가는 경로가 원천 차단된다.
            wait_for_phase_gate("phase2")

            # 2단계 AI 스크리닝 (신규 대상만)
            update_progress(45, "2단계: AI 문체 스크리닝 중...")
            add_log(f"[2단계] LLM 스크리닝 시작 (모델: {req.screening_provider}/{req.screening_model})")

            provider_screening = create_provider(
                provider_name=req.screening_provider,
                api_key=screening_key,
                model_screening=req.screening_model,
                model_verify="",  # 사용되지 않음
                cost_tracker=cost_tracker
            )

            results_by_student = {r["student"]: r for r in new_results}
            submissions_to_screen = []
            for r in new_results:
                submissions_to_screen.append({
                    "student": r["student"],
                    "filename": r["student"],
                    "text": r.get("text", "")
                })

            def _on_stage2_item_done(screened_sub: dict):
                """학생 1명의 2단계 스크리닝이 끝날 때마다 즉시 결과에 반영하고 UI를 갱신한다.
                각 호출은 완전히 독립된 신규 API 요청의 결과이므로, 다음 학생 처리에
                이전 학생의 판정이나 대화 맥락이 전혀 영향을 주지 않는다 (할루시네이션 전이 차단)."""
                r = results_by_student.get(screened_sub["student"])
                if r is None:
                    return
                r["ai_score"] = screened_sub.get("ai_score", 0)
                stage2_info = screened_sub.get("stage2", {})
                r["stage2"] = stage2_info
                if stage2_info.get("error"):
                    add_log(f"⚠️ 경고: {r['student']} 학생의 스크리닝 중 오류가 발생했습니다. (사유: {stage2_info.get('rationale')})")
                # r은 analysis_state["results"] 내 동일 객체이므로 별도 재대입 없이 UI 즉시 반영

            run_stage2(
                submissions_to_screen, provider_screening, config,
                check_cb=check_control_state, on_item_done=_on_stage2_item_done,
            )

            # 등급 산출: 재개된 항목까지 포함한 전체 점수 분포를 기준으로 백분위를 계산하되,
            # 재개된 항목은 이미 확정(immutable)된 체크포인트이므로 원래 tier를 그대로 보존한다.
            resumed_tier_map = {student: rec.get("tier") for student, rec in completed_map.items()}
            calculate_tiers(resumed_results + new_results, config.get("tier", {}).get("threshold_percentile", 30))
            for r in resumed_results:
                original_tier = resumed_tier_map.get(r["student"])
                if original_tier is not None:
                    r["tier"] = original_tier

            # (tier 산출 결과도 동일 객체 in-place 갱신으로 UI에 이미 반영됨)

            # 3단계 사실 검증 대상자 확정 (사용자 주도형 듀얼 패널 선택, no_verify가 최우선)
            if req.no_verify:
                add_log("[3단계] 옵션에 의해 사실 검증을 생략합니다.")
                candidates = []
            else:
                # 듀얼 패널 모달용 후보 페이로드: 각 학생 항목에 이전 단계(1·2단계)
                # 판단 결과 요약을 함께 실어 좌측 패널의 뱃지로 렌더링된다.
                selection_payload = []
                for r in new_results:
                    stage2_info = r.get("stage2") or {}
                    selection_payload.append({
                        "student": r["student"],
                        "student_id": r.get("student_id", ""),
                        "student_name": r.get("student_name") or r["student"],
                        "book_title": r.get("book_title") or stage2_info.get("book_title") or "",
                        "rule_score": r.get("rule_score", 0),
                        "risk_grade": r.get("risk_grade", ""),
                        "ai_score": r.get("ai_score", 0),
                        "signals": (stage2_info.get("signals") or [])[:3],
                        "tier": r.get("tier", ""),
                    })

                # 초기 자동 선택(Auto-selection): 1·2단계 결과가 임계치를 초과한
                # 위험군(tier 상/최우선)을 미리 체크. verify_all 옵션이면 전원 선택.
                if req.verify_all:
                    preselected_keys = [r["student"] for r in new_results]
                else:
                    preselected_keys = [
                        r["student"] for r in new_results
                        if r.get("tier") in ("상", "최우선")
                    ]

                # 사용자가 [최종 검증 확정]을 누를 때까지 대기 (그동안 토큰 소모 0).
                selected_keys = set(wait_for_stage3_selection(selection_payload, preselected_keys))
                candidates = [r for r in new_results if r["student"] in selected_keys]
                add_log(f"[3단계] 사용자 확정 검증 대상: {len(candidates)}명")

            update_progress(70, "3단계: 사실 검증 및 팩트시트 대조 중...")

            candidate_keys = {c["student"] for c in candidates}
            non_candidates = [r for r in new_results if r["student"] not in candidate_keys]

            if candidates:
                add_log(f"[3단계] 사실 검증 시작 (모델: {req.verify_provider}/{req.verify_model})")

                provider_verify = create_provider(
                    provider_name=req.verify_provider,
                    api_key=verify_key,
                    model_screening="",  # 사용되지 않음
                    model_verify=req.verify_model,
                    cost_tracker=cost_tracker
                )

                def _ensure_factsheet_jit(book_title: str) -> Optional[str]:
                    """Step C (Just-In-Time Evaluation): run_stage3가 검증 도중 해당 도서를
                    '만나는 시점'에만 호출한다.
                    - Cache Hit(Phase 1.5 선제 생성분 또는 과거 세션분): 로컬 팩트시트 즉시
                      반환 → LLM 호출·토큰 소모 0.
                    - Cache Miss: 그 시점에 해당 도서 1권만 LLM으로 생성하고 즉시
                      book_cache.json에 Append한 뒤 검증을 이어간다 (생성 중 UI 스피너 표시).
                    """
                    try:
                        if not book_title or book_title.lower() == "unknown":
                            return None
                        author = _resolve_author(book_title)
                        # 확정된 저자를 같은 도서의 모든 후보 레코드에 반영 (데이터 유실 방지)
                        for cand in candidates:
                            cand_title = cand.get("stage2", {}).get("book_title") or cand.get("book_title")
                            if cand_title == book_title:
                                if "stage2" not in cand:
                                    cand["stage2"] = {}
                                cand["stage2"]["author"] = author
                                cand["author"] = author
                        content = ensure_book_factsheet_cached(
                            book_title, author, provider_verify,
                            book_cache, factsheets_dir, req.no_web,
                        )
                        return content or None
                    except Exception as ex:
                        # Defensive: 팩트시트 확보 실패 시에도 해당 도서만 '검증 불가' 처리하고 계속 진행
                        logger.error(f"[JIT] 도서 '{book_title}' 팩트시트 확보 에러 (검증 계속 진행): {ex}")
                        return None

                def _on_stage3_item_done(cand: dict):
                    """피실험자 1명의 3단계 검증이 끝나는 즉시(Atomic Unit 완료) 최종 결과를 확정하고
                    append-only로 영속화 및 UI에 실시간 반영한다. 각 검증은 독립된 API 호출이므로
                    이 학생의 판정이 다음 학생 처리에 전혀 영향을 주지 않는다 (할루시네이션 전이 차단)."""
                    s3 = cand.get("stage3", {})
                    if s3.get("error"):
                        add_log(f"⚠️ 경고: {cand['student']} 학생의 사실 검증 중 오류가 발생했습니다. (사유: {s3.get('overall')})")
                    claims = s3.get("claims", [])
                    contradiction_count = sum(1 for cl in claims if cl.get("verdict") == "모순")
                    cand["contradictions"] = contradiction_count
                    cand["hallucination_score"] = s3.get("hallucination_score", 0)
                    cand["interview_questions"] = s3.get("interview_questions", [])
                    if contradiction_count > 0:
                        cand["tier"] = "최우선"

                    _finalize_and_persist_student(cand)

                # ensure_cb=_ensure_factsheet_jit: 팩트시트를 사전 일괄 생성하지 않고,
                # 검증 루프가 각 도서를 만나는 순간 Cache Hit/Miss를 판정해 JIT 확보한다.
                run_stage3(
                    candidates, provider_verify, factsheets_dir, config, req.no_web,
                    check_cb=check_control_state, on_item_done=_on_stage3_item_done,
                    ensure_cb=_ensure_factsheet_jit,
                )

            # 3단계 대상이 아닌 학생은 2단계 완료 및 등급 확정 시점에 이미 Atomic Unit 처리가
            # 끝난 것이므로 즉시 확정 및 영속화한다.
            for r in non_candidates:
                _finalize_and_persist_student(r)

        # 재개된 결과 + 신규 처리 결과 병합 (원본 제출 순서 유지)
        results_by_student_final = {r["student"]: r for r in (resumed_results + new_results)}
        results = [
            results_by_student_final[s["student"]]
            for s in submissions
            if s["student"] in results_by_student_final
        ]

        # 7. 최종 데이터 포맷팅 및 CSV 준비
        update_progress(90, "최종 결과 리포트 작성 중...")
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
        os.makedirs(output_dir, exist_ok=True)
        
        for r in results:
            if not r.get("book_title"):
                r["book_title"] = r.get("stage2", {}).get("book_title") or ""
            if "rule_details" in r and not r.get("rule_evidence"):
                evidence_parts = []
                for check_name, detail in r["rule_details"].items():
                    if detail.get("score", 0) > 0:
                        evidence_parts.append(f"[{check_name}] {detail['score']:.1f}점")
                r["rule_evidence"] = "; ".join(evidence_parts)
            if not r.get("ai_signals"):
                r["ai_signals"] = r.get("stage2", {}).get("signals", [])
            metadata = r.get("metadata")
            if metadata and not r.get("edit_time_min"):
                r["edit_time_min"] = metadata.get("total_time_minutes", "")
                
        # 리포트 생성
        for r in results:
            if r.get("stage3") or r.get("tier") in ("상", "최우선"):
                report_path = generate_report(r, output_dir)
                r["report"] = report_path
            else:
                r["report"] = ""
                
        # CSV 저장
        csv_path = os.path.join(output_dir, "screening_summary.csv")
        generate_csv(results, csv_path)
        add_log(f"💾 종합 리포트 CSV 저장 완료: {csv_path}")
        
        # 비용 요약
        cost_summary = cost_tracker.get_summary()
        
        with state_lock:
            analysis_state["status"] = "completed"
            analysis_state["progress"] = 100
            analysis_state["step"] = "분석 완료"
            analysis_state["results"] = results
            analysis_state["cost_summary"] = cost_summary

        # 최종 세션 스냅샷 저장 (State Portability — 타 PC에서 이어하기 가능)
        save_session_progress(results, cost_summary, status="completed")
        add_log(f"💾 프로젝트 세션 저장 완료: {active_session_path() or '(활성 프로젝트 없음)'}")

        add_log("🎉 전체 파이프라인 분석이 성공적으로 끝났습니다!")
        
    except Exception as e:
        logger.exception("분석 스레드 실패")
        with state_lock:
            if "강제 종료" in str(e):
                analysis_state["status"] = "stopped"
                analysis_state["step"] = "강제 종료됨"
                analysis_state["error_message"] = str(e)
            else:
                analysis_state["status"] = "error"
                analysis_state["error_message"] = str(e)
                analysis_state["step"] = "에러 발생"
        add_log(f"❌ 에러가 발생했습니다: {e}")

@app.post("/api/analyze")
def start_analysis(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    global analysis_state
    
    # 로그인 세션 데이터 가져오기
    session_data = global_user_manager.get_session_data()
    if not session_data:
        raise HTTPException(status_code=401, detail="먼저 로그인하셔야 분석을 돌릴 수 있습니다.")

    # 분석 결과는 활성 프로젝트의 session.json에 영속화되므로 활성 프로젝트가 필수다.
    _require_active_project()

    with state_lock:
        if analysis_state["status"] == "running":
            raise HTTPException(status_code=400, detail="이미 다른 분석이 진행 중입니다.")
            
        # 초기화
        analysis_state["status"] = "running"
        analysis_state["progress"] = 0
        analysis_state["step"] = "준비 중..."
        analysis_state["logs"] = []
        # [DB형 상태 관리] results는 파이프라인 실행 전 적재된 영속 데이터셋이므로
        # 절대 초기화하지 않는다 — 파이프라인이 이 데이터셋을 그대로 순회한다.
        analysis_state["cost_summary"] = {}
        analysis_state["error_message"] = ""
        analysis_state["awaiting_phase"] = None
        analysis_state["stage3_selection"] = None
        analysis_state["factsheet_generating"] = None
        stop_event.clear()
        pause_event.set()
        phase_gate_event.clear()
        stage3_selection_event.clear()
        stage3_selected["keys"] = None

    config = load_config()
    
    # 백그라운드 스레드에서 분석 실행
    thread = threading.Thread(
        target=run_pipeline_thread,
        args=(req, session_data, config)
    )
    thread.daemon = True
    thread.start()
    
    return {"message": "분석 시작"}

@app.post("/api/analyze/pause")
def pause_analysis():
    global analysis_state
    with state_lock:
        if analysis_state["status"] != "running":
            raise HTTPException(status_code=400, detail="진행 중인 분석이 없습니다.")
    pause_event.clear()
    return {"message": "일시정지 요청 완료"}

@app.post("/api/analyze/resume")
def resume_analysis():
    global analysis_state
    with state_lock:
        if analysis_state["status"] != "paused":
            raise HTTPException(status_code=400, detail="일시정지 상태가 아닙니다.")
    pause_event.set()
    return {"message": "재개 요청 완료"}

@app.post("/api/analyze/stop")
def stop_analysis():
    global analysis_state
    with state_lock:
        if analysis_state["status"] not in ("running", "paused", "awaiting_phase", "awaiting_stage3_selection"):
            raise HTTPException(status_code=400, detail="진행 중인 분석이 없습니다.")
    stop_event.set()
    pause_event.set()  # 대기 중인 스레드를 깨우기 위함
    phase_gate_event.set()  # 단계 게이트에서 대기 중인 스레드를 깨우기 위함
    stage3_selection_event.set()  # 3단계 대상 선택 게이트에서 대기 중인 스레드를 깨우기 위함
    return {"message": "강제 종료 요청 완료"}

@app.post("/api/analyze/next-phase")
def next_phase_analysis():
    """Task 5: [다음 단계 진행] 버튼 — 단계 경계에서 대기 중인 파이프라인에 진행 허가를 내린다."""
    global analysis_state
    with state_lock:
        if analysis_state["status"] != "awaiting_phase":
            raise HTTPException(status_code=400, detail="현재 다음 단계로 진행할 수 있는 대기 상태가 아닙니다.")
    phase_gate_event.set()
    return {"message": "다음 단계 진행 요청 완료"}

class Stage3SelectionRequest(BaseModel):
    students: list[str]

@app.post("/api/analyze/stage3-selection")
def confirm_stage3_selection(req: Stage3SelectionRequest):
    """듀얼 패널 모달의 [최종 검증 확정] 실행 훅.

    우측 패널에 적재된 학생 키 배열을 받아 3단계 Batch 검증 대상으로 확정하고,
    선택 게이트에서 대기 중인 파이프라인 스레드를 깨운다. 이 호출이 오기 전까지
    파이프라인은 어떤 LLM API도 호출하지 않는다 (토큰 소모 0 대기).
    """
    global analysis_state
    with state_lock:
        if analysis_state["status"] != "awaiting_stage3_selection":
            raise HTTPException(status_code=400, detail="현재 3단계 대상 선택 대기 상태가 아닙니다.")
        valid_keys = {
            c["student"] for c in (analysis_state.get("stage3_selection") or {}).get("candidates", [])
        }

    # 후보 목록에 없는 키는 무시 (중복 제거 + 순서 보존)
    selected = [s for s in dict.fromkeys(req.students) if s in valid_keys]
    stage3_selected["keys"] = selected
    stage3_selection_event.set()
    return {"message": f"3단계 검증 대상 {len(selected)}명 확정 완료", "selected_count": len(selected)}

@app.post("/api/analyze/reset")
def reset_analysis():
    global analysis_state
    with state_lock:
        analysis_state["status"] = "idle"
        analysis_state["error_message"] = ""
    return {"message": "상태 초기화 완료"}

@app.post("/api/analyze/enrich-factsheet")
async def enrich_factsheet(req: EnrichRequest):
    # 1. 로그인 세션 및 API 키 획득
    session = global_user_manager.get_session_data()
    if not session:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    api_keys = session.get("api_keys", {})

    config = load_config()
    provider_name = req.verify_provider or config.get("verify", {}).get("provider", "gemini")
    model_name = req.verify_model or config.get("verify", {}).get("model", "gemini-2.5-flash")

    api_key = api_keys.get(provider_name)
    if not api_key:
        raise HTTPException(status_code=400, detail=f"3단계 검증을 위한 {provider_name} API Key가 등록되지 않았습니다. API 키를 먼저 등록해 주세요.")

    # 1. 전달받은 도서명과 저자명으로 고유 캐시 키 복원
    cache_key = normalize_cache_key(req.book_title, req.author)
    
    # 2. 기존 generate_factsheet보다 훨씬 강력하고 촘촘한 시스템 프롬프트 정의
    deep_prompt = (
        f"당신은 도서 '{req.book_title}'({req.author})에 대한 고해상도 사실 검증 전문가입니다. "
        f"인터넷 검색을 통해 해당 도서 내의 구체적인 핵심 개념, 저자의 핵심 주장, 역사적/과학적 사실적 수치, "
        f"고유 명사 리스트를 일반적인 수준보다 3배 이상 디테일하고 풍부하게 심층 조사하여 마크다운 포맷의 팩트시트를 재생성하세요."
    )
    
    # 3. LLM 및 검색 엔진을 재가동하여 고밀도 팩트시트 콘텐츠 생성
    try:
        cost_tracker = CostTracker(config)
        provider_verify = create_provider(
            provider_name=provider_name,
            api_key=api_key,
            model_screening="",
            model_verify=model_name,
            cost_tracker=cost_tracker
        )
        enriched_content = provider_verify.generate_enriched_factsheet(req.book_title, prompt_override=deep_prompt)
    except Exception as e:
        logger.error(f"심층 팩트시트 보강 API 에러: {e}")
        raise HTTPException(status_code=500, detail=f"팩트시트 보강 실패: {str(e)}")

    if not enriched_content or "에러:" in enriched_content or "실패했습니다" in enriched_content:
         raise HTTPException(status_code=500, detail="LLM이 팩트시트 보강 결과를 생성하지 못했습니다.")

    # 4. 단일 마스터 파일(`book_cache.json`)에서 해당 Key의 데이터만 완벽하게 덮어쓰기(Overwrite) 및 동기화
    #    (book_cache_lock: 파이프라인/선제생성 스레드와의 load-modify-save 경합 방지)
    with book_cache_lock:
        book_cache = load_book_cache()
        book_cache[cache_key] = {
            "book_title": req.book_title,
            "author": req.author,
            "factsheet": enriched_content,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "is_enriched": True
        }
        save_book_cache(book_cache)
    
    # 5. 기존의 로컬 factsheets/ 디렉토리 내 마크다운 파일도 즉시 동기화 업데이트
    try:
        factsheets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "factsheets")
        os.makedirs(factsheets_dir, exist_ok=True)
        normalized_title = _normalize_title(req.book_title)
        if normalized_title:
            filepath = os.path.join(factsheets_dir, f"{normalized_title}.md")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(enriched_content)
    except Exception as e:
        logger.warning(f"로컬 factsheet 파일 동기화 저장 실패: {e}")

    # UI 중앙 로그창에 알림 추가
    add_log(f"⚡ [온디맨드 보강 완료] '{req.book_title}'({req.author}) 도서 팩트시트 심층 보강 완료!")

    return {"status": "success", "message": f"'{req.book_title}' 도서 팩트시트 심층 보강 완료"}

@app.get("/api/analyze/status")
def get_analysis_status():
    """[Guard — Idle State Audit] 이 엔드포인트는 순수 읽기 전용(Read-Only)이다.
    UI가 2초 주기로 폴링하더라도 인메모리 스냅샷 반환 외에 어떤 LLM API 호출·
    파일 재연산도 발생하지 않는다. 토큰을 소비하는 로직은 오직 명시적 사용자
    클릭 이벤트(POST /api/analyze, /next-phase, /stage3-selection, /enrich-factsheet)
    에서만 발화된다 (Strict Event-Driven Control)."""
    with state_lock:
        return {
            "status": analysis_state["status"],
            "progress": analysis_state["progress"],
            "step": analysis_state["step"],
            "logs": analysis_state["logs"],
            "cost_summary": analysis_state["cost_summary"],
            "error_message": analysis_state["error_message"],
            "awaiting_phase": analysis_state.get("awaiting_phase"),
            "stage3_selection": analysis_state.get("stage3_selection"),
            # Cache Miss로 JIT 생성 중인 도서명 (UI 스피너 "'{도서명}' 팩트시트 신규 생성 중...")
            "factsheet_generating": analysis_state.get("factsheet_generating"),
        }

@app.get("/api/results")
def get_results():
    with state_lock:
        return {
            "results": analysis_state["results"],
            "cost_summary": analysis_state["cost_summary"]
        }

# -------------------------------------------------------------
# 보고서 파일 및 CSV 다운로드 API
# -------------------------------------------------------------
@app.get("/api/export")
def export_csv():
    """analysis_state["results"]의 현재 인메모리 스냅샷을 즉시 CSV로 동적 직렬화하여 반환한다.

    파이프라인이 idle/running/paused/awaiting_phase/completed 등 어떤 상태에 있든
    (진행 중이라도) 그 시점까지 누적된 결과를 그대로 최신 CSV로 재생성해 다운로드할 수 있다.
    """
    with state_lock:
        results_snapshot = list(analysis_state["results"])

    if not results_snapshot:
        raise HTTPException(status_code=404, detail="아직 생성된 분석 결과가 없습니다. 먼저 분석을 시작해 주세요.")

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, "screening_summary.csv")

    try:
        generate_csv(results_snapshot, csv_path)
    except Exception as e:
        logger.error(f"CSV 동적 직렬화 실패: {e}")
        raise HTTPException(status_code=500, detail=f"CSV 생성 실패: {e}")

    return FileResponse(csv_path, media_type="text/csv", filename="screening_summary.csv")

def _csv_val_to_float(val) -> Optional[float]:
    """CSV 셀 값을 float로 변환한다. 비어있거나 변환 불가하면 None (결측 판정용)."""
    if val is None:
        return None
    val_s = str(val).strip()
    if not val_s:
        return None
    try:
        return float(val_s)
    except (ValueError, TypeError):
        return None

@app.post("/api/import")
async def import_csv(file: UploadFile = File(...)):
    """이전에 다운로드한 screening_summary.csv를 업로드하여 analysis_state["results"]를 복구한다.

    - 완전히 처리된(rule_score/ai_score 존재, 검증이 필요한 등급이면 hallucination_score도 존재) 행은
      screening_results.jsonl 체크포인트에 백필하여, 다음 분석 실행 시 기존 재개(Resume) 엔진이
      해당 학생을 자동으로 스킵(토큰 소모 0)하도록 만든다.
    - 점수가 누락/비어있는(Delta) 행은 체크포인트에 올리지 않아 다음 실행 시 자동으로 재처리된다.
    """
    with state_lock:
        if analysis_state["status"] in ("running", "paused", "awaiting_phase"):
            raise HTTPException(status_code=400, detail="분석이 진행 중일 때는 결과를 복구할 수 없습니다. 먼저 정지해 주세요.")

    try:
        raw_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"파일 읽기 실패: {e}")

    # generate_csv()가 utf-8-sig(BOM)로 저장하므로 동일 인코딩으로 복원, 실패 시 cp949 재시도
    text = None
    for encoding in ("utf-8-sig", "cp949", "utf-8"):
        try:
            text = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise HTTPException(status_code=400, detail="CSV 파일 인코딩을 해석할 수 없습니다 (UTF-8/CP949 지원).")

    try:
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CSV 파싱 실패: {e}")

    if not rows:
        raise HTTPException(status_code=400, detail="CSV 파일에 데이터 행이 없습니다.")

    completed_map = load_completed_results()
    imported: list = []
    backfilled = 0
    incomplete = 0

    for row in rows:
        try:
            student = (row.get("student") or "").strip()
            if not student:
                continue

            rule_score = _csv_val_to_float(row.get("rule_score"))
            ai_score = _csv_val_to_float(row.get("ai_score"))
            hallucination_score = _csv_val_to_float(row.get("hallucination_score"))
            tier = (row.get("tier") or "").strip() or None

            ai_signals_raw = row.get("ai_signals") or ""
            ai_signals = [s.strip() for s in ai_signals_raw.split(";") if s.strip()]

            try:
                contradictions = int(float(row.get("contradictions"))) if (row.get("contradictions") or "").strip() else 0
            except (ValueError, TypeError):
                contradictions = 0

            book_title = (row.get("book_title") or "").strip()

            record = {
                "student": student,
                "student_id": (row.get("student_id") or "").strip(),
                "student_name": (row.get("student_name") or "").strip() or student,
                "book_title": book_title,
                "rule_score": rule_score if rule_score is not None else 0,
                "rule_evidence": row.get("rule_evidence") or "",
                "rule_details": {},
                "edit_time_min": row.get("edit_time_min") or "",
                "ai_score": ai_score if ai_score is not None else 0,
                "ai_signals": ai_signals,
                "stage2": {"book_title": book_title or None, "signals": ai_signals, "rationale": ""},
                "contradictions": contradictions,
                "hallucination_score": hallucination_score if hallucination_score is not None else 0,
                "tier": tier or "하",
                "stage3": ({"hallucination_score": hallucination_score, "claims": []} if hallucination_score is not None else {}),
                "report": row.get("report") or "",
                "text": "",
                "file_type": "imported_csv",
                "file_path": "",
                "metadata": None,
            }

            # Delta Detection: 규칙/스크리닝 점수가 없으면 미완료. 상위 등급인데 검증 결과가
            # 없으면(hallucination_score 결측) 검증이 누락된 것으로 간주해 미완료 처리한다.
            is_complete = rule_score is not None and ai_score is not None
            if is_complete and tier in ("상", "최우선") and hallucination_score is None:
                is_complete = False

            if is_complete and student not in completed_map:
                append_screening_result(record)
                completed_map[student] = record
                backfilled += 1
            elif not is_complete:
                incomplete += 1

            imported.append(record)
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"CSV 행 파싱 실패 (해당 행 스킵, 나머지는 계속 진행): {e}")
            continue

    if not imported:
        raise HTTPException(status_code=400, detail="유효한 학생 데이터를 CSV에서 찾지 못했습니다.")

    with state_lock:
        analysis_state["results"] = imported
        analysis_state["status"] = "idle"
        analysis_state["error_message"] = ""

    # CSV 복구 내용도 세션 스냅샷에 동기화 (재기동 시 자동 복원 대상)
    save_session_progress(imported, status="restored")

    msg = f"CSV 업로드 복구 완료: 총 {len(imported)}명 로드, 체크포인트 백필 {backfilled}명, 재처리 필요(Delta) {incomplete}명"
    add_log(f"📥 {msg}")

    return {
        "message": msg,
        "total": len(imported),
        "backfilled": backfilled,
        "incomplete": incomplete,
    }

# -------------------------------------------------------------
# 세션 진행 상태 파일 API (State Portability — 작업 이어하기 및 파일 공유)
# book_cache.json(글로벌 도서 캐시)과는 완전히 분리된 세션 전용 파일이다.
# -------------------------------------------------------------
@app.get("/api/session/info")
def get_session_info():
    """UI 상단 표기용: 현재 저장 중인 세션 파일명·경로·최종 저장 시각."""
    return session_file_info()

@app.get("/api/session/download")
def download_session_file():
    """session_progress.json을 그대로 다운로드한다 (타 PC로 작업 이관용)."""
    path = active_session_path()
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="활성 프로젝트의 세션 파일이 없습니다. 먼저 프로젝트를 선택해 주세요.")
    active = get_active_project() or {}
    download_name = f"{active.get('name') or 'project'}_session.json"
    return FileResponse(path, media_type="application/json", filename=download_name)

@app.post("/api/session/upload")
async def upload_session_file(file: UploadFile = File(...)):
    """진행 상태 파일을 업로드하여 세션을 복원(Resume)한다.

    - 파일 이름이 변경되어 있어도 내용 스키마(schema/version)만 일치하면 복원된다.
    - 복원된 내용은 '현재 활성 프로젝트'의 세션으로 저장된다.
    - 완전히 처리된 학생은 활성 프로젝트의 screening_results.jsonl 체크포인트에
      백필되어, 다음 분석 실행 시 자동으로 스킵된다 (중복 API 호출/토큰 소모 0).
    """
    _require_active_project()
    with state_lock:
        if analysis_state["status"] in ("running", "paused", "awaiting_phase", "awaiting_stage3_selection"):
            raise HTTPException(status_code=400, detail="분석이 진행 중일 때는 세션을 복원할 수 없습니다. 먼저 정지해 주세요.")

    try:
        raw_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"파일 읽기 실패: {e}")

    try:
        data = parse_session_payload(raw_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"세션 파일 검증 실패: {e}")

    results = data["results"]

    # 완료된 학생을 체크포인트(jsonl)에 백필 → 재분석 시 자동 스킵 (Resume 엔진 재사용)
    completed_map = load_completed_results()
    backfilled = 0
    incomplete = 0
    for r in results:
        is_complete = r.get("rule_score") is not None and r.get("ai_score") is not None
        if is_complete and r.get("tier") in ("상", "최우선") and r.get("hallucination_score") in (None, ""):
            is_complete = False
        if is_complete and r["student"] not in completed_map:
            append_screening_result(r)
            completed_map[r["student"]] = r
            backfilled += 1
        elif not is_complete:
            incomplete += 1

    with state_lock:
        analysis_state["results"] = results
        analysis_state["cost_summary"] = data.get("cost_summary", {})
        analysis_state["status"] = "idle"
        analysis_state["error_message"] = ""

    # 업로드된 내용을 현재 세션 파일로 저장 (이후 이 컴퓨터에서 계속 이어짐)
    save_session_progress(results, data.get("cost_summary"), status="restored")

    msg = (
        f"세션 복원 완료 (원본 저장 시각: {data.get('saved_at', '미상')}): "
        f"총 {len(results)}명 로드, 체크포인트 백필 {backfilled}명, 재처리 필요 {incomplete}명"
    )
    add_log(f"📥 {msg}")
    return {
        "message": msg,
        "total": len(results),
        "backfilled": backfilled,
        "incomplete": incomplete,
        "saved_at": data.get("saved_at"),
    }

def markdown_to_html(md: str) -> str:
    lines = md.split("\n")
    html_lines = []
    in_table = False
    
    for line in lines:
        line_strip = line.strip()
        if line_strip.startswith("# "):
            html_lines.append(f"<h2>{line_strip[2:]}</h2>")
            continue
        if line_strip.startswith("## "):
            html_lines.append(f"<h3>{line_strip[3:]}</h3>")
            continue
        if line_strip.startswith("### "):
            html_lines.append(f"<h4>{line_strip[4:]}</h4>")
            continue
        if line_strip == "---":
            html_lines.append("<hr>")
            continue
        if line_strip.startswith("- "):
            html_lines.append(f"<ul><li>{line_strip[2:]}</li></ul>")
            continue
        if line_strip and line_strip[0].isdigit() and line_strip[1:3] == ". ":
            html_lines.append(f"<ol start='{line_strip[0]}'><li>{line_strip[3:]}</li></ol>")
            continue
        if line_strip.startswith("|") and line_strip.endswith("|"):
            parts = [p.strip() for p in line_strip.split("|")[1:-1]]
            if all(p.startswith("-") or p == "" for p in parts):
                continue
            if not in_table:
                html_lines.append("<table class='fact-table'><thead>")
                in_table = True
            
            if html_lines[-1] == "<table class='fact-table'><thead>":
                html_lines.append("<tr>" + "".join(f"<th>{p}</th>" for p in parts) + "</tr></thead><tbody>")
            else:
                html_lines.append("<tr>" + "".join(f"<td>{p}</td>" for p in parts) + "</tr>")
            continue
        else:
            if in_table:
                html_lines.append("</tbody></table>")
                in_table = False
                
        if line_strip.startswith("```"):
            if line_strip == "```":
                html_lines.append("</pre>")
            else:
                html_lines.append("<pre class='code-block'>")
            continue
            
        if line_strip:
            import re
            processed = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", line)
            html_lines.append(f"<p>{processed}</p>")
            
    if in_table:
        html_lines.append("</tbody></table>")
        
    return "\n".join(html_lines)

@app.get("/api/reports/{student}")
def get_report(student: str):
    # run_pipeline_thread에서 generate_report(r, output_dir)를 outputs/ 디렉토리 자체에 저장하므로
    # (outputs/reports/ 하위 폴더가 아님) 실제 저장 경로와 동일하게 맞춘다.
    reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    file_path = os.path.join(reports_dir, f"{student}.md")
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="해당 학생의 상세 마크다운 리포트가 존재하지 않습니다.")
        
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            md_content = f.read()
        
        html_content = markdown_to_html(md_content)
        return {
            "student": student,
            "markdown": md_content,
            "html": html_content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"리포트 로드 실패: {e}")

# -------------------------------------------------------------
# Task 2: 로컬 도서 인벤토리 조회 & 팩트시트 파일 뷰어 API
# -------------------------------------------------------------
@app.get("/api/book-inventory")
def get_book_inventory():
    """book_cache.json(로컬 도서 인벤토리)에 기록된 도서 목록을 최신순으로 반환합니다."""
    book_cache = load_book_cache()
    items = []
    for cache_key, entry in book_cache.items():
        book_title_raw = entry.get("book_title", "") or ""
        author_raw = (entry.get("author") or "").strip()

        # 하위 호환: 과거에 '도서명(저자명)' 파싱 이전에 저장되어 author가 비어있거나
        # "Unknown"으로 남은 레코드는 조회 시점에 비파괴적으로 재분리하여 표시한다.
        if not author_raw or author_raw.lower() == "unknown":
            parsed_title, parsed_author = parse_book_title_author(book_title_raw)
            display_title = parsed_title or book_title_raw
            display_author = parsed_author or author_raw
        else:
            display_title = book_title_raw
            display_author = author_raw

        items.append({
            "cache_key": cache_key,
            "book_title": display_title,
            "author": display_author,
            "updated_at": entry.get("updated_at", ""),
            "is_enriched": bool(entry.get("is_enriched", False)),
        })
    items.sort(key=lambda x: x["updated_at"], reverse=True)
    return {"books": items, "total": len(items)}

@app.get("/api/book-inventory/{cache_key}/factsheet")
def get_book_factsheet(cache_key: str):
    """특정 도서(cache_key)의 팩트시트 파일을 즉시 열람합니다 (파일 핸들러 조회 → 렌더링)."""
    book_cache = load_book_cache()
    entry = book_cache.get(cache_key)
    if not entry:
        raise HTTPException(status_code=404, detail="해당 도서가 book_cache.json 인벤토리에 존재하지 않습니다.")

    book_title = entry.get("book_title", "")
    factsheets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "factsheets")
    normalized_title = _normalize_title(book_title) if book_title else ""
    file_path = os.path.join(factsheets_dir, f"{normalized_title}.md") if normalized_title else ""

    md_content = ""
    if file_path and os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                md_content = f.read()
        except OSError as e:
            logger.warning(f"팩트시트 파일 읽기 실패({file_path}): {e}")

    # 로컬 .md 파일이 아직 없다면 book_cache.json에 캐시된 원문으로 대체
    if not md_content.strip():
        md_content = entry.get("factsheet", "")

    if not md_content.strip():
        raise HTTPException(status_code=404, detail="해당 도서의 팩트시트 데이터 라인을 찾을 수 없습니다.")

    return {
        "cache_key": cache_key,
        "book_title": book_title,
        "author": entry.get("author", ""),
        "file_path": file_path,
        "markdown": md_content,
        "html": markdown_to_html(md_content),
    }

# -------------------------------------------------------------
# 정적 파일 서빙
# -------------------------------------------------------------
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

# -------------------------------------------------------------
# 싱글톤 UserManager 인스턴스
# -------------------------------------------------------------
global_user_manager = UserManager()

# -------------------------------------------------------------
# 서버 기동 시 세션 자동 복원 (State Persistence):
# 마지막 session_progress.json 스냅샷이 있으면 결과 목록을 즉시 복구하여
# 재기동 후에도 UI에서 이전 작업을 그대로 이어볼 수 있게 한다.
# -------------------------------------------------------------
# [다중 프로젝트 아키텍처] 서버 기동 시 자동 복원은 수행하지 않는다.
# 로그인 후 [프로젝트 대시보드]에서 프로젝트를 activate하는 시점에 해당
# 프로젝트의 session.json이 로드된다. 구버전 단일 session_progress.json은
# GET /api/projects 최초 조회 시 프로젝트로 자동 이관(migrate_legacy_session)된다.

# 앱 실행 시 모든 프로필의 API 키를 모아 모델 캐시를 백그라운드에서 동적 갱신
trigger_bg_refresh_all_profiles()

def open_browser():
    try:
        webbrowser.open("http://localhost:8000")
    except Exception as e:
        logger.error(f"브라우저 열기 실패: {e}")

if __name__ == "__main__":
    import uvicorn
    import warnings

    # Trio 또는 기타 프레임워크의 예외 처리기 관련 RuntimeWarning 필터링
    warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*sys.excepthook.*")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.call_later(1.0, open_browser)
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
