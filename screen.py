#!/usr/bin/env python3
"""AI 사용 의심 선별·검증 도구 — 메인 CLI 진입점 (Supabase DB 계정 연동).

사용법:
    python screen.py ./submissions/              # 기본 실행
    python screen.py ./submissions/ --verify-all # 전원 3단계
    python screen.py ./submissions/ --no-verify  # 3단계 생략
    python screen.py ./submissions/ --no-web     # 팩트시트 자동 생성 금지
    python screen.py register                    # 회원가입 (username + 비밀번호)
    python screen.py login                       # 로그인 (세션 토큰 발급)
    python screen.py logout                      # 로그아웃 (토큰 폐기)
    python screen.py whoami                      # 현재 로그인 계정 확인
    python screen.py delete-account              # 본인 계정 삭제
    python screen.py select-model                # 모델 변경 (웹 대시보드 안내)
"""

from dotenv import load_dotenv
load_dotenv()  # SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / ENCRYPTION_KEY 로드

import argparse
import getpass
import os
import sys
import yaml
from pathlib import Path
from typing import Optional

from database import DatabaseError
from utils.user_manager import UserManager
from utils.cost_tracker import CostTracker
from utils.docx_metadata import extract_docx_metadata
from utils.file_reader import read_submissions
from utils.report_generator import generate_csv, generate_report, calculate_tiers, print_console_summary
from providers import create_provider
from stages.stage1_rules import run_stage1
from stages.stage2_screening import run_stage2
from stages.stage3_verify import run_stage3, ensure_factsheet, estimate_cost


def load_config(config_path: str = None) -> dict:
    """config.yaml 로드."""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_legacy_session(raw_session: Optional[dict]) -> Optional[dict]:
    if not raw_session:
        return None
    api_keys = raw_session.get("api_keys", {})
    if isinstance(api_keys, list):
        api_keys_dict = {k: "" for k in api_keys}
    else:
        api_keys_dict = api_keys
        
    default_models = raw_session.get("default_models", {})
    provider = default_models.get("screening_provider")
    if not provider and api_keys_dict:
        provider = list(api_keys_dict.keys())[0]
        
    api_key = api_keys_dict.get(provider, "") if provider else ""
    
    return {
        "profile_name": raw_session.get("profile_name") or raw_session.get("name"),
        "provider": provider or "",
        "api_key": api_key,
        "model_screening": default_models.get("screening_model") or "",
        "model_verify": default_models.get("verify_model") or ""
    }


# -------------------------------------------------------------
# CLI 세션 토큰 저장소 (~/.ai_screening/cli_token)
# 로그인 성공 시 발급된 무상태 Bearer 토큰을 로컬에 보관한다.
# (구버전 profiles.yaml 평문 API 키 저장 방식은 완전히 폐기됨.)
# -------------------------------------------------------------
_TOKEN_FILE = Path.home() / ".ai_screening" / "cli_token"


def _save_token(token: str) -> None:
    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_FILE.write_text(token, encoding="utf-8")


def _load_token() -> Optional[str]:
    if not _TOKEN_FILE.exists():
        return None
    try:
        return _TOKEN_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _clear_token() -> None:
    try:
        _TOKEN_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _current_user(um: UserManager) -> Optional[dict]:
    """저장된 토큰으로 로그인 사용자 행을 복원한다 (만료/위조 시 None)."""
    token = _load_token()
    if not token:
        return None
    return um.get_user_by_token(token)


def cmd_register(um: UserManager):
    """회원가입 서브커맨드 (username + 비밀번호, bcrypt 해시 저장)."""
    print("\n=== 회원가입 ===")
    username = input("사용자 ID: ").strip()
    password = getpass.getpass("비밀번호 (8자 이상): ")
    password2 = getpass.getpass("비밀번호 확인: ")
    if password != password2:
        print("❌ 비밀번호가 일치하지 않습니다.")
        return False
    try:
        um.register(username, password)
    except ValueError as e:
        print(f"❌ 가입 실패: {e}")
        return False
    print(f"✅ '{username}' 계정이 생성되었습니다. 'python screen.py login'으로 로그인하세요.")
    print("   API 키 등록/모델 선택은 웹 대시보드에서 진행합니다.")
    return True


def cmd_login(um: UserManager):
    """로그인 서브커맨드 (비밀번호 검증 → 세션 토큰 로컬 저장)."""
    print("\n=== 로그인 ===")
    username = input("사용자 ID: ").strip()
    password = getpass.getpass("비밀번호: ")

    result = um.login(username, password)
    if not result:
        print("\n❌ 사용자 ID 또는 비밀번호가 올바르지 않습니다.")
        return False

    _save_token(result["token"])
    dm = result.get("default_models", {})
    print(f"\n✅ '{username}' 계정으로 로그인했습니다.")
    print(f"   등록된 API 키: {', '.join(result.get('api_keys') or []) or '없음'}")
    print(f"   스크리닝 모델: {dm.get('screening_provider')}/{dm.get('screening_model')}")
    print(f"   검증 모델: {dm.get('verify_provider')}/{dm.get('verify_model')}")
    return True


def cmd_logout(um: UserManager):
    """로그아웃 서브커맨드 (로컬 토큰 폐기)."""
    user = _current_user(um)
    _clear_token()
    if user:
        print(f"✅ '{user['username']}' 계정에서 로그아웃했습니다.")
    else:
        print("현재 로그인된 계정이 없습니다 (토큰 정리 완료).")


def cmd_whoami(um: UserManager):
    """현재 로그인 계정 확인 서브커맨드."""
    user = _current_user(um)
    if not user:
        print("로그인되어 있지 않습니다. 'python screen.py login'을 실행하세요.")
        return
    profile = um.get_public_profile(user)
    dm = profile["default_models"]
    print(f"\n=== 현재 계정 ===")
    print(f"  사용자 ID : {profile['name']}")
    print(f"  API 키    : {', '.join(profile['api_keys']) or '없음'}")
    print(f"  스크리닝  : {dm.get('screening_provider')}/{dm.get('screening_model')}")
    print(f"  검증      : {dm.get('verify_provider')}/{dm.get('verify_model')}\n")


def cmd_delete_account(um: UserManager):
    """본인 계정 삭제 서브커맨드 (프로젝트/체크포인트 cascade 삭제)."""
    user = _current_user(um)
    if not user:
        print("먼저 로그인하세요.")
        return
    confirm = input(f"계정 '{user['username']}'와 모든 프로젝트 데이터를 삭제하시겠습니까? (y/n): ")
    if confirm.lower() == "y":
        if um.delete_user(user["id"]):
            _clear_token()
            print("✅ 계정이 삭제되었습니다.")
        else:
            print("❌ 계정 삭제에 실패했습니다.")
    else:
        print("삭제가 취소되었습니다.")


def cmd_select_model(um: UserManager, config: dict):
    """모델 변경 서브커맨드."""
    print("모델 변경은 웹 대시보드(분석 설정 패널)를 사용해 주세요.")


def ensure_login(um: UserManager, config: dict) -> Optional[dict]:
    """로그인 상태 확인, 필요 시 로그인 유도.

    Returns:
        로그인된 프로필 정보 dict (provider, api_key, model_screening, model_verify)
        또는 None (실패 시). API 키는 이 시점에 DB에서 복호화된다.
    """
    user = _current_user(um)
    if not user:
        print("로그인이 필요합니다.")
        if not cmd_login(um):
            return None
        user = _current_user(um)
        if not user:
            return None
    return _get_legacy_session(um.get_session_data(user))


def run_pipeline(args, config: dict, session: dict):
    """메인 파이프라인 실행."""
    submissions_dir = args.submissions_dir

    # 1. 제출물 로드
    print(f"\n📂 제출물 로드: {submissions_dir}")
    submissions = read_submissions(submissions_dir)
    if not submissions:
        print("❌ 제출물을 찾을 수 없습니다.")
        return

    print(f"   {len(submissions)}개 제출물 발견\n")

    # docx 메타데이터 추출 + filename 추가
    for sub in submissions:
        sub["filename"] = sub["student"]  # stage2에서 참조
        if sub["file_type"] == "docx":
            sub["metadata"] = extract_docx_metadata(sub["file_path"])
        else:
            sub["metadata"] = None

    # 2. 프로바이더 초기화
    provider = create_provider(
        provider_name=session["provider"],
        api_key=session["api_key"],
        model_screening=session["model_screening"],
        model_verify=session["model_verify"],
    )
    cost_tracker = CostTracker(config)

    # 3. 1단계: 규칙 기반 점수 (전수)
    print("=" * 60)
    print("📋 1단계: 규칙 기반 점수 (API 미사용)")
    print("=" * 60)
    for sub in submissions:
        result = run_stage1(sub["text"], sub.get("metadata"), sub["student"], config)
        sub["rule_score"] = result["rule_score"]
        sub["rule_details"] = result["details"]
        print(f"  {sub['student']:20s}  rule_score={sub['rule_score']:.1f}")
    print()

    # 4. 2단계: API 스크리닝 (전수)
    print("=" * 60)
    print(f"🤖 2단계: LLM 스크리닝 ({session['model_screening']})")
    print("=" * 60)
    submissions = run_stage2(submissions, provider, config)
    for sub in submissions:
        ai_display = sub.get("ai_score", "ERROR")
        print(f"  {sub['student']:20s}  ai_score={ai_display}")
    print()

    # 비용 업데이트
    usage = provider.get_usage()
    for stage_name, stage_usage in usage["usage"].items():
        model_name = usage["model_screening"] if stage_name == "screening" else usage["model_verify"]
        if any(v > 0 for v in stage_usage.values()):
            cost_tracker.add_usage(
                model=model_name,
                input_tokens=stage_usage["input_tokens"],
                output_tokens=stage_usage["output_tokens"],
                cache_read_tokens=stage_usage["cache_read_tokens"],
                cache_write_tokens=stage_usage["cache_write_tokens"],
            )
    if usage["web_search_count"] > 0:
        cost_tracker.add_web_search(usage["web_search_count"])

    # 5. 등급 1차 산정
    results = calculate_tiers(submissions, config.get("tier", {}).get("threshold_percentile", 30))

    # 6. 3단계 실행 여부 결정
    base_dir = os.path.dirname(os.path.abspath(__file__))
    factsheets_dir = os.path.join(base_dir, "factsheets")
    reports_dir = os.path.join(base_dir, "reports")
    os.makedirs(factsheets_dir, exist_ok=True)
    os.makedirs(reports_dir, exist_ok=True)

    if args.no_verify:
        print("⏭️  3단계 생략 (--no-verify)\n")
    else:
        # 대상 선정
        if args.verify_all:
            candidates = [r for r in results]
            print(f"🔍 3단계 대상: 전원 ({len(candidates)}명) (--verify-all)")
        else:
            candidates = [r for r in results if r.get("tier") in ("상", "최우선")]
            print(f"🔍 3단계 대상: {len(candidates)}명 (등급 '상' 이상)")

        if candidates:
            # 비용 추정 및 확인
            count, estimated_usd = estimate_cost(candidates, config)
            print(f"   예상 검증 대상: {count}명")
            print(f"   예상 비용: ${estimated_usd:.4f} USD")

            confirm = input("\n   계속하시겠습니까? (y/n): ")
            if confirm.lower() == "y":
                print()
                print("=" * 60)
                print(f"🔬 3단계: 팩트시트 기반 사실 검증 ({session['model_verify']})")
                print("=" * 60)

                candidates = run_stage3(
                    candidates=candidates,
                    provider=provider,
                    factsheets_dir=factsheets_dir,
                    config=config,
                    no_web=args.no_web,
                )

                # 3단계 결과를 원래 results에 반영
                candidate_map = {c["student"]: c for c in candidates}
                for r in results:
                    if r["student"] in candidate_map:
                        c = candidate_map[r["student"]]
                        s3 = c.get("stage3", {})
                        claims = s3.get("claims", [])
                        contradiction_count = sum(1 for cl in claims if cl.get("verdict") == "모순")
                        r.update({
                            "stage3": s3,
                            "contradictions": contradiction_count,
                            "hallucination_score": s3.get("hallucination_score", ""),
                            "interview_questions": s3.get("interview_questions", []),
                        })
                        # 모순 발견 시 최우선 승격
                        if contradiction_count > 0:
                            r["tier"] = "최우선"

                # 비용 갱신
                usage = provider.get_usage()
                for stage_name, stage_usage in usage["usage"].items():
                    model_name = usage["model_screening"] if stage_name == "screening" else usage["model_verify"]
                    if any(v > 0 for v in stage_usage.values()):
                        cost_tracker.add_usage(
                            model=model_name,
                            input_tokens=stage_usage["input_tokens"],
                            output_tokens=stage_usage["output_tokens"],
                            cache_read_tokens=stage_usage["cache_read_tokens"],
                            cache_write_tokens=stage_usage["cache_write_tokens"],
                        )
                if usage["web_search_count"] > 0:
                    cost_tracker.add_web_search(usage["web_search_count"])

                print()
            else:
                print("   3단계를 건너뜁니다.\n")
        else:
            print("   3단계 대상자가 없습니다.\n")

    # 7. 리포트 생성 및 CSV 준비
    print("=" * 60)
    print("📊 결과 생성")
    print("=" * 60)

    # CSV용 데이터 준비
    for r in results:
        # book_title: stage2에서 가져오기
        if not r.get("book_title"):
            r["book_title"] = r.get("stage2", {}).get("book_title") or ""

        # rule_evidence: rule_details에서 요약 생성
        if "rule_details" in r and not r.get("rule_evidence"):
            evidence_parts = []
            for check_name, detail in r["rule_details"].items():
                if detail.get("score", 0) > 0:
                    evidence_parts.append(f"[{check_name}] {detail['score']:.1f}점")
            r["rule_evidence"] = "; ".join(evidence_parts)

        # ai_signals: stage2에서 가져오기
        if not r.get("ai_signals"):
            r["ai_signals"] = r.get("stage2", {}).get("signals", [])

        # edit_time_min: metadata에서 가져오기
        metadata = r.get("metadata")
        if metadata and not r.get("edit_time_min"):
            r["edit_time_min"] = metadata.get("total_time_minutes", "")

    # 3단계를 거친 학생 리포트 생성
    for r in results:
        if r.get("stage3_claims") or r.get("tier") in ("상", "최우선"):
            report_path = generate_report(r, reports_dir)
            r["report"] = report_path
        else:
            r["report"] = ""

    # CSV 생성
    csv_path = os.path.join(os.path.dirname(submissions_dir.rstrip("/\\")), "results.csv")
    generate_csv(results, csv_path)
    print(f"\n  📄 CSV: {csv_path}")
    print(f"  📁 리포트: {reports_dir}/")

    # 8. 콘솔 요약 (최우선 + 상만)
    print()
    print_console_summary(results)

    # 9. 비용 로그
    print()
    cost_tracker.print_summary()


def main():
    # 1. sys.argv 전처리: 서브커맨드가 없으면 'run' 커맨드를 강제로 주입
    commands = {'register', 'login', 'logout', 'whoami', 'delete-account', 'select-model', 'run'}
    has_command = False
    for arg in sys.argv[1:]:
        if arg in commands:
            has_command = True
            break
        if arg in ('-h', '--help'):
            has_command = True
            break
            
    if not has_command:
        # 첫 번째 실질적인 인자(플래그 제외)의 앞에 'run' 커맨드를 삽입
        idx = 1
        while idx < len(sys.argv) and sys.argv[idx].startswith('-'):
            idx += 1
        sys.argv.insert(idx, 'run')

    parser = argparse.ArgumentParser(
        description="독서 수행평가 AI 사용 의심 선별·검증 도구",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="점수는 증거가 아니며 최종 판단은 교사의 구술 면담으로 확인합니다.",
    )

    # 글로벌 옵션 등록
    parser.add_argument("--config", default=None, help="config.yaml 경로 지정")

    subparsers = parser.add_subparsers(dest="command", help="서브커맨드")

    # 서브커맨드 정의
    subparsers.add_parser("register", help="회원가입 (username + 비밀번호)")
    subparsers.add_parser("login", help="계정 로그인 (세션 토큰 발급)")
    subparsers.add_parser("logout", help="로그아웃 (토큰 폐기)")
    subparsers.add_parser("whoami", help="현재 로그인 계정 확인")
    subparsers.add_parser("delete-account", help="본인 계정 삭제")
    subparsers.add_parser("select-model", help="모델 변경 (웹 대시보드 안내)")

    # run 서브커맨드 정의 (기본 실행 모드)
    run_parser = subparsers.add_parser("run", help="분석 실행")
    run_parser.add_argument("submissions_dir", nargs="?", help="제출물 폴더/파일 경로")
    run_parser.add_argument("--verify-all", action="store_true", help="전원 3단계 실행")
    run_parser.add_argument("--no-verify", action="store_true", help="3단계 생략")
    run_parser.add_argument("--no-web", action="store_true", help="팩트시트 자동 생성 금지")

    args = parser.parse_args()

    # 설정 로드
    config = load_config(args.config)
    um = UserManager()

    # 서브커맨드 처리
    try:
        if args.command == "register":
            cmd_register(um)
            return
        elif args.command == "login":
            cmd_login(um)
            return
        elif args.command == "logout":
            cmd_logout(um)
            return
        elif args.command == "whoami":
            cmd_whoami(um)
            return
        elif args.command == "delete-account":
            cmd_delete_account(um)
            return
        elif args.command == "select-model":
            cmd_select_model(um, config)
            return
    except DatabaseError as e:
        print(f"❌ 데이터베이스 연결 오류: {e}")
        print("   .env의 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 설정을 확인하세요.")
        sys.exit(1)

    # 메인 실행: 제출물 폴더 또는 파일 경로 필수
    if not args.submissions_dir:
        run_parser.print_help()
        print("\n❌ 제출물 폴더 또는 파일 경로를 지정하세요.")
        sys.exit(1)

    if not os.path.exists(args.submissions_dir):
        print(f"❌ 경로를 찾을 수 없습니다: {args.submissions_dir}")
        sys.exit(1)

    # 로그인 확인
    session = ensure_login(um, config)
    if not session:
        print("❌ 로그인에 실패했습니다. 프로그램을 종료합니다.")
        sys.exit(1)

    print(f"\n[Profile] {session.get('profile_name', '알 수 없음')} | {session['provider']} | {session['model_screening']} / {session['model_verify']}")

    # 파이프라인 실행
    try:
        run_pipeline(args, config, session)
    except KeyboardInterrupt:
        print("\n\n⚠️ 사용자에 의해 중단되었습니다.")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ 예기치 않은 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
