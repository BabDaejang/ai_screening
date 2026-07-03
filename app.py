from dotenv import load_dotenv
load_dotenv() # .env 로드

import asyncio
import json
import logging
import os
import threading
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
from stages.stage3_verify import run_stage3, ensure_factsheet

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="AI 의심 선별 도구 웹 UI")

# 전역 상태 관리
analysis_state = {
    "status": "idle",  # idle, running, completed, error
    "progress": 0,
    "step": "",
    "logs": [],
    "results": [],
    "cost_summary": {},
    "error_message": ""
}

# 락 객체
state_lock = threading.Lock()

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

# -------------------------------------------------------------
# 모델 캐시 로드, 저장 및 백그라운드 갱신 헬퍼 함수
# -------------------------------------------------------------
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models_cache.json")

def load_models_cache() -> dict:
    """models_cache.json에서 캐싱된 모델 목록을 로드합니다."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        logger.error(f"모델 캐시 로드 실패: {e}")
        return {}

def save_models_cache(cache_data: dict):
    """models_cache.json에 모델 캐시를 저장합니다. 기존 캐시와 병합합니다."""
    try:
        existing = load_models_cache()
        existing.update(cache_data)
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
    """tkinter를 사용해 네이티브 OS 폴더 선택 창을 열고 선택된 경로를 반환합니다."""
    import threading
    result = {"path": None, "error": None}
    ready = threading.Event()

    def _open_dialog():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()                    # 메인 윈도우 숨기기
            root.attributes("-topmost", True)  # 항상 최상단 표시
            start_dir = initial if initial and os.path.isdir(initial) else os.path.expanduser("~")
            selected = filedialog.askdirectory(
                parent=root,
                title="제출물 폴더를 선택하세요",
                initialdir=start_dir,
                mustexist=True,
            )
            root.destroy()
            if selected:
                result["path"] = selected.replace("/", "\\")
        except Exception as e:
            result["error"] = str(e)
        finally:
            ready.set()

    t = threading.Thread(target=_open_dialog, daemon=True)
    t.start()
    ready.wait(timeout=120)  # 최대 2분 대기

    if result["error"]:
        raise HTTPException(status_code=500, detail=f"폴더 선택 창 오류: {result['error']}")

    return {"path": result["path"]}  # 취소 시 path=null


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
            raise Exception("제출물 파일(.txt, .docx)이 발견되지 않았습니다.")
            
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
        
        # 1단계 규칙 기반 검사
        update_progress(25, "1단계: 규칙 기반 검사 중...")
        results = []
        for i, sub in enumerate(submissions, 1):
            add_log(f"[1단계] ({i}/{len(submissions)}) {sub['student']} 검사 중...")
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
            results.append(res_item)
            
        # 2단계 AI 스크리닝
        update_progress(45, "2단계: AI 문체 스크리닝 중...")
        add_log(f"[2단계] LLM 스크리닝 시작 (모델: {req.screening_provider}/{req.screening_model})")
        
        provider_screening = create_provider(
            provider_name=req.screening_provider,
            api_key=screening_key,
            model_screening=req.screening_model,
            model_verify="",  # 사용되지 않음
            cost_tracker=cost_tracker
        )
        
        submissions_to_screen = []
        for r in results:
            submissions_to_screen.append({
                "student": r["student"],
                "filename": r["student"],
                "text": r["text"]
            })
            
        screened_submissions = run_stage2(submissions_to_screen, provider_screening, config)
        
        # 2단계 결과를 results에 머지
        for r, screened in zip(results, screened_submissions):
            r["ai_score"] = screened.get("ai_score", 0)
            stage2_info = screened.get("stage2", {})
            r["stage2"] = stage2_info
            if stage2_info.get("error"):
                add_log(f"⚠️ 경고: {r['student']} 학생의 스크리닝 중 오류가 발생했습니다. (사유: {stage2_info.get('rationale')})")
            
        # 등급 1차 임시 산출
        results = calculate_tiers(results, config.get("tier", {}).get("threshold_percentile", 30))
        
        # 3단계 사실 검증 대상자 선별
        update_progress(70, "3단계: 사실 검증 및 팩트시트 대조 중...")
        candidates = []
        if req.verify_all:
            candidates = results
            add_log("[3단계] 모든 학생을 대상으로 검증을 진행합니다.")
        elif req.no_verify:
            add_log("[3단계] 옵션에 의해 사실 검증을 생략합니다.")
        else:
            candidates = [r for r in results if r.get("tier") in ("상", "최우선")]
            add_log(f"[3단계] 선별 대상자: {len(candidates)}명")
            
        if candidates and not req.no_verify:
            add_log(f"[3단계] 사실 검증 시작 (모델: {req.verify_provider}/{req.verify_model})")
            
            provider_verify = create_provider(
                provider_name=req.verify_provider,
                api_key=verify_key,
                model_screening="",  # 사용되지 않음
                model_verify=req.verify_model,
                cost_tracker=cost_tracker
            )
            
            factsheets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "factsheets")
            run_stage3(candidates, provider_verify, factsheets_dir, config, req.no_web)
            
            # 3단계 결과를 원래 results에 반영
            candidate_map = {c["student"]: c for c in candidates}
            for r in results:
                if r["student"] in candidate_map:
                    c = candidate_map[r["student"]]
                    s3 = c.get("stage3", {})
                    if s3.get("error"):
                        add_log(f"⚠️ 경고: {r['student']} 학생의 사실 검증 중 오류가 발생했습니다. (사유: {s3.get('overall')})")
                    claims = s3.get("claims", [])
                    contradiction_count = sum(1 for cl in claims if cl.get("verdict") == "모순")
                    r.update({
                        "stage3": s3,
                        "contradictions": contradiction_count,
                        "hallucination_score": s3.get("hallucination_score", 0),
                        "interview_questions": s3.get("interview_questions", []),
                    })
                    if contradiction_count > 0:
                        r["tier"] = "최우선"
                        
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
        
    config = load_config()
    
    # 백그라운드 스레드에서 분석 실행
    thread = threading.Thread(
        target=run_pipeline_thread,
        args=(req, session_data, config)
    )
    thread.daemon = True
    thread.start()
    
    return {"message": "분석 시작"}

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
    loop = asyncio.get_event_loop()
    loop.call_later(1.0, open_browser)
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
