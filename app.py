from dotenv import load_dotenv
load_dotenv() # .env 로드

import asyncio
import json
import logging
import os
import re
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from utils.user_manager import UserManager
from utils.cost_tracker import CostTracker
from utils.docx_metadata import extract_docx_metadata
from utils.file_reader import read_submissions
from utils.report_generator import generate_csv, generate_report, calculate_tiers
from providers import create_provider
from stages.stage1_rules import run_stage1
from stages.stage2_screening import run_stage2
from stages.stage3_verify import run_stage3, ensure_factsheet, _normalize_title

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="AI 의심 선별 도구 웹 UI")

# 전역 상태 관리
analysis_state = {
    "status": "idle",  # idle, running, completed, error, paused
    "progress": 0,
    "step": "",
    "logs": [],
    "results": [],
    "cost_summary": {},
    "error_message": ""
}

# 락 객체 및 실행 제어 이벤트
state_lock = threading.Lock()
stop_event = threading.Event()
pause_event = threading.Event()
pause_event.set()

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
    submissions_dir: str
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
    """book_cache.json 마스터 파일에 캐시 딕셔너리를 안전하게 저장합니다."""
    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "book_cache.json")
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=4)
    except OSError as e:
        logger.error(f"book_cache.json 저장 실패: {e}")

def normalize_cache_key(title: str, author: str) -> str:
    """공백 및 파일 시스템 금지 문자를 제거하여 고유 키를 정형화합니다."""
    cleaned_title = re.sub(r'[\s\\/:*?"<>|]', '', title).strip()
    cleaned_author = re.sub(r'[\s\\/:*?"<>|]', '', author).strip()
    return f"{cleaned_title}_{cleaned_author}"

# -------------------------------------------------------------
# 2단계 스크리닝 결과 Append-Only 영속화 & 체크포인트-재개(Resume) 엔진
# (screening_results.jsonl)
# -------------------------------------------------------------
RESULTS_JSONL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screening_results.jsonl")

def load_completed_results() -> dict:
    """screening_results.jsonl을 스캔하여 이미 완료된 [학번_성명] 인덱스를 로드합니다.

    손상된 라인은 건너뛰고 계속 진행합니다 (Fault Tolerance). 반환된 딕셔너리는
    이후 루프 진입 전 `if target in completed_map: skip` 판단에 사용되어
    중복 API 호출과 토큰 낭비를 원천 차단합니다.
    """
    completed: dict = {}
    if not os.path.exists(RESULTS_JSONL_PATH):
        return completed
    try:
        with open(RESULTS_JSONL_PATH, "r", encoding="utf-8") as f:
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
        with open(RESULTS_JSONL_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
        student = result.get("student", "?")
        msg = f"[SUCCESS: Saved Screening Result for {student} to screening_results.jsonl]"
        print(msg)
        add_log(msg)
    except OSError as e:
        logger.error(f"screening_results.jsonl 저장 실패: {e}")

def lookup_author(book_title: str, provider) -> str:
    """책 제목을 기반으로 AI 모델을 호출하여 원작자/저자명을 역추적(Reverse Lookup)합니다."""
    if not book_title or book_title.lower() == "unknown":
        return "Unknown"
    
    system_prompt = "당신은 도서 저자명을 찾고 JSON 형태로만 반환하는 도서 도우미입니다. 반드시 아래 JSON 형식으로만 응답하세요.\n{\n  \"author\": \"저자명\"\n}"
    try:
        res = provider.screen(system_prompt, f"도서명: {book_title}")
        if isinstance(res, dict) and "author" in res and res["author"]:
            return str(res["author"]).strip()
    except Exception as e:
        logger.error(f"저자 역추적 중 에러: {e}")
    return "Unknown"

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
# 분석 API & 백그라운드 태스크
# -------------------------------------------------------------
def run_pipeline_thread(req: AnalyzeRequest, session_data: dict, config: dict):
    global analysis_state
    
    try:
        update_progress(5, "제출물 파일 읽는 중...")
        add_log(f"📂 제출물 디렉토리: {req.submissions_dir}")
        
        # API 키 검증
        api_keys = session_data.get("api_keys", {})
        screening_key = api_keys.get(req.screening_provider)
        verify_key = api_keys.get(req.verify_provider)
        
        if not screening_key:
            raise Exception(f"2단계 스크리닝을 위한 {req.screening_provider} API Key가 등록되지 않았습니다.")
        if not req.no_verify and not verify_key:
            raise Exception(f"3단계 사실 검증을 위한 {req.verify_provider} API Key가 등록되지 않았습니다.")
            
        submissions = read_submissions(req.submissions_dir)
        if not submissions:
            raise Exception("제출물 파일이 발견되지 않았습니다. 지원 형식: Excel, CSV, PDF, TXT, DOCX")
            
        add_log(f"✅ {len(submissions)}개 제출물 로드 완료.")

        # docx 메타데이터 추출
        update_progress(15, "메타데이터 추출 중...")
        for sub in submissions:
            sub["filename"] = sub["student"]
            if sub["file_type"] == "docx":
                sub["metadata"] = extract_docx_metadata(sub["file_path"])
            else:
                sub["metadata"] = None

        # CostTracker 설정
        cost_tracker = CostTracker(config)

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
                resumed_results.append(completed_map[sub["student"]])
            else:
                submissions_to_process.append(sub)

        if resumed_results:
            add_log(f"🔁 체크포인트 발견: {len(resumed_results)}명은 이전에 이미 완료되어 스킵합니다 (중복 API 호출/토큰 소모 0).")
        add_log(f"▶️ 신규 처리 대상: {len(submissions_to_process)}명")

        # UI State Synchronization: 재개된 결과를 [선별 결과 목록]에 즉시 반영
        with state_lock:
            analysis_state["results"] = list(resumed_results)

        new_results: list = []

        def _finalize_and_persist_student(r: dict):
            """피실험자 1명(Atomic Unit)의 처리가 최종 완료되는 즉시 로컬 파일에
            append-only로 영속화하고, 동시에 상위 UI 레이어에 실시간으로 반영한다."""
            append_screening_result(r)
            with state_lock:
                analysis_state["results"] = resumed_results + list(new_results)

        if not submissions_to_process:
            add_log("✅ 모든 대상이 체크포인트에 이미 존재하여 신규 스크리닝을 생략합니다.")
        else:
            # 1단계 규칙 기반 검사 (신규 대상만)
            update_progress(25, "1단계: 규칙 기반 검사 중...")
            for i, sub in enumerate(submissions_to_process, 1):
                check_control_state("1단계", i, len(submissions_to_process), sub["student"])
                add_log(f"[1단계] ({i}/{len(submissions_to_process)}) {sub['student']} 검사 중...")
                stage1_res = run_stage1(sub["text"], sub["metadata"], sub["filename"], config)
                res_item = {
                    "student": sub["student"],
                    "text": sub["text"],
                    "file_type": sub["file_type"],
                    "file_path": sub["file_path"],
                    "metadata": sub["metadata"],
                    "rule_score": stage1_res["rule_score"],
                    "rule_details": stage1_res["details"]
                }
                new_results.append(res_item)

                # UI State Synchronization: 대상 식별 및 도서 매핑 완료 즉시 반영
                with state_lock:
                    analysis_state["results"] = resumed_results + list(new_results)

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
                    "text": r["text"]
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
                with state_lock:
                    analysis_state["results"] = resumed_results + list(new_results)

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

            with state_lock:
                analysis_state["results"] = resumed_results + list(new_results)

            # 3단계 사실 검증 대상자 선별 (신규 처리 대상 중에서만, no_verify가 최우선)
            update_progress(70, "3단계: 사실 검증 및 팩트시트 대조 중...")
            if req.no_verify:
                add_log("[3단계] 옵션에 의해 사실 검증을 생략합니다.")
                candidates = []
            elif req.verify_all:
                candidates = list(new_results)
                add_log("[3단계] 모든 신규 학생을 대상으로 검증을 진행합니다.")
            else:
                candidates = [r for r in new_results if r.get("tier") in ("상", "최우선")]
                add_log(f"[3단계] 선별 대상자: {len(candidates)}명")

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

                factsheets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "factsheets")
                os.makedirs(factsheets_dir, exist_ok=True)

                # book_cache.json (Fact Sheet 레지스트리) 로드
                book_cache = load_book_cache()

                for cand in candidates:
                    book_title = None
                    try:
                        # 1. 도서명 확보
                        book_title = cand.get("stage2", {}).get("book_title") or cand.get("book_title")
                        if not book_title or book_title.lower() == "unknown":
                            continue

                        # 2. 저자명 자동 추적 및 메타데이터 보완 (Author Auto-Correction)
                        author = cand.get("stage2", {}).get("author") or cand.get("author")
                        if not author or author.strip() == "":
                            add_log(f"🔍 '{book_title}' 도서의 저자 정보 누락 감지. 저자 역추적 중...")
                            author = lookup_author(book_title, provider_verify)
                            add_log(f"✅ 저자 추적 완료: '{book_title}' -> '{author}'")

                            # 데이터 구조에 강제 업데이트하여 데이터 유실 방지
                            if "stage2" not in cand:
                                cand["stage2"] = {}
                            cand["stage2"]["author"] = author
                            cand["author"] = author

                        # 3. 고유 키(Key) 생성
                        cache_key = normalize_cache_key(book_title, author)

                        # 4. Fact Sheet Cache-Look-up (CASE A/B 분기)
                        if cache_key in book_cache:
                            # CASE A (로컬에 존재): 재생성 생략, 캐시된 팩트시트 재사용
                            add_log(f"💾 캐시 히트! '{cache_key}' 도서 정보를 book_cache.json에서 불러옵니다. (토큰 0)")
                            factsheet_content = book_cache[cache_key].get("factsheet", "")
                        else:
                            # CASE B (로컬에 부재): 팩트시트 생성 태스크 즉시 트리거
                            if req.no_web:
                                add_log(f"🌐 캐시 미스했으나 no_web 옵션 활성화 상태로 생략: {cache_key}")
                                factsheet_content = ""
                            else:
                                add_log(f"🌐 캐시 미스! '{cache_key}' 도서의 팩트시트를 생성합니다. (웹 검색/LLM 가동)")
                                factsheet_content = provider_verify.generate_factsheet(book_title)

                                # Checkpoint Saving: 전역 캐시 딕셔너리에 즉시 병합 저장 (Write-Through)
                                book_cache[cache_key] = {
                                    "book_title": book_title,
                                    "author": author,
                                    "factsheet": factsheet_content,
                                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
                                }
                                save_book_cache(book_cache)
                                success_msg = f"[SUCCESS: Saved Fact Sheet for {book_title} to local file]"
                                print(success_msg)
                                add_log(success_msg)

                        # 5. 로컬 팩트시트 파일 생성 (stages.stage3_verify와의 연동용)
                        if factsheet_content:
                            normalized_title = _normalize_title(book_title)
                            if normalized_title:
                                filepath = os.path.join(factsheets_dir, f"{normalized_title}.md")
                                with open(filepath, "w", encoding="utf-8") as f:
                                    f.write(factsheet_content)
                    except Exception as ex:
                        # Defensive: 특정 항목 대조 중 에러가 나더라도 continue로 강제 진행
                        logger.error(f"도서 '{book_title}' 사실검증 캐싱 준비 에러 (루프 계속 진행): {ex}")
                        continue

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

                run_stage3(
                    candidates, provider_verify, factsheets_dir, config, req.no_web,
                    check_cb=check_control_state, on_item_done=_on_stage3_item_done,
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
        
    with state_lock:
        if analysis_state["status"] == "running":
            raise HTTPException(status_code=400, detail="이미 다른 분석이 진행 중입니다.")
            
        # 초기화
        analysis_state["status"] = "running"
        analysis_state["progress"] = 0
        analysis_state["step"] = "준비 중..."
        analysis_state["logs"] = []
        analysis_state["results"] = []
        analysis_state["cost_summary"] = {}
        analysis_state["error_message"] = ""
        stop_event.clear()
        pause_event.set()
        
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
        if analysis_state["status"] not in ("running", "paused"):
            raise HTTPException(status_code=400, detail="진행 중인 분석이 없습니다.")
    stop_event.set()
    pause_event.set()  # 대기 중인 스레드를 깨우기 위함
    return {"message": "강제 종료 요청 완료"}

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
    with state_lock:
        return {
            "status": analysis_state["status"],
            "progress": analysis_state["progress"],
            "step": analysis_state["step"],
            "logs": analysis_state["logs"],
            "cost_summary": analysis_state["cost_summary"],
            "error_message": analysis_state["error_message"]
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
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs", "screening_summary.csv")
    if not os.path.exists(csv_path):
        raise HTTPException(status_code=404, detail="CSV 결과 파일이 존재하지 않습니다. 먼저 분석을 돌려주세요.")
    return FileResponse(csv_path, media_type="text/csv", filename="screening_summary.csv")

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
    reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs", "reports")
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
# 정적 파일 서빙
# -------------------------------------------------------------
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

# -------------------------------------------------------------
# 싱글톤 UserManager 인스턴스
# -------------------------------------------------------------
global_user_manager = UserManager()

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
