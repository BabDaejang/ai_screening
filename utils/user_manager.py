"""사용자 프로필 관리 모듈.

API 키를 평문으로 프로필에 저장하고,
로그인/로그아웃, 모델 선택 등의 기능을 제공합니다.
프로필 파일: ~/.ai_screening/profiles.yaml
"""

import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

def write_env_keys(env_path: Path, keys_dict: dict) -> bool:
    """.env 파일에서 특정 키들의 값을 안전하게 업데이트하거나 추가합니다."""
    content = ""
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            pass
            
    lines = content.splitlines()
    updated_lines = []
    handled_keys = set()
    
    # 기존 라인 분석 후 매칭되는 키 교체
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            updated_lines.append(line)
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            # 프로바이더명 -> .env 환경 변수명 맵핑
            mapping = {"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
            matched_provider = None
            for prov, env_name in mapping.items():
                if k == env_name:
                    matched_provider = prov
                    break
            
            if matched_provider and matched_provider in keys_dict:
                new_val = keys_dict[matched_provider]
                updated_lines.append(f"{k}={new_val}")
                handled_keys.add(matched_provider)
            else:
                updated_lines.append(line)
        else:
            updated_lines.append(line)
            
    # 신규 입력된 키 추가
    mapping = {"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
    for prov, env_name in mapping.items():
        if prov in keys_dict and prov not in handled_keys:
            updated_lines.append(f"{env_name}={keys_dict[prov]}")
            
    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(updated_lines) + "\n")
        return True
    except OSError as e:
        logger.error(f".env 파일 저장 실패: {e}")
        return False

# 프로필 저장 경로
_PROFILES_DIR = Path.home() / ".ai_screening"
_PROFILES_FILE = _PROFILES_DIR / "profiles.yaml"


class UserManager:
    """사용자 프로필 관리 클래스."""

    def __init__(self, profiles_path: Optional[str] = None):
        """UserManager 초기화.

        Args:
            profiles_path: 프로필 YAML 파일 경로. None이면 기본 경로 사용.
        """
        self._profiles_path = Path(profiles_path) if profiles_path else _PROFILES_FILE
        self._data: dict = self._load()
        # 메모리 키 캐시 - 시작 시 현재 프로필에서 자동 복원
        self._current_decrypted_keys: dict[str, str] = self._restore_keys_from_file()

    def _restore_keys_from_file(self) -> dict:
        """파일에 저장된 current_profile의 API 키를 복원합니다 (재기동 후 자동 복원)."""
        current = self._data.get("current_profile")
        if not current:
            return {}
        profile = self._data["profiles"].get(current, {})
        return dict(profile.get("api_keys", {}))


    def _load(self) -> dict:
        """프로필 파일을 로드합니다."""
        if not self._profiles_path.exists():
            return {"current_profile": None, "profiles": {}}
        try:
            with open(self._profiles_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            # 필수 키 보장
            data.setdefault("current_profile", None)
            data.setdefault("profiles", {})
            return data
        except yaml.YAMLError as e:
            logger.error("프로필 파일 파싱 오류: %s", e)
            return {"current_profile": None, "profiles": {}}
        except OSError as e:
            logger.error("프로필 파일 읽기 실패: %s", e)
            return {"current_profile": None, "profiles": {}}

    def _save(self) -> bool:
        """프로필 데이터를 파일에 저장합니다."""
        try:
            self._profiles_path.parent.mkdir(parents=True, exist_ok=True)
            
            # [안전 장치] 저장 전, 현재 활성화된 프로필의 api_keys가 메모리 캐시보다 비어있는 경우 복원 보장
            current = self._data.get("current_profile")
            if current and current in self._data.get("profiles", {}):
                profile = self._data["profiles"][current]
                # 파일용 저장 데이터의 api_keys가 비어있고 메모리에 키가 존재한다면 덮어쓰기 방지
                if not profile.get("api_keys") and self._current_decrypted_keys:
                    profile["api_keys"] = dict(self._current_decrypted_keys)
            
            with open(self._profiles_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    self._data, f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )
            return True
        except OSError as e:
            logger.error("프로필 저장 실패: %s", e)
            return False

    def add_profile(
        self,
        name: str,
        password: Optional[str] = None,
        provider: Optional[str] = None,
        model_screening: Optional[str] = None,
        model_verify: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> bool:
        """새 프로필을 추가합니다 (비밀번호 없는 평문 관리 구조)."""
        if name in self._data["profiles"]:
            logger.error("이미 존재하는 프로필 이름: %s", name)
            return False

        self._data["profiles"][name] = {
            "api_keys": {},
            "default_models": {
                "screening_provider": provider or "",
                "screening_model": model_screening or "",
                "verify_provider": provider or "",
                "verify_model": model_verify or "",
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # 레거시 호환성 및 즉시 등록 지원
        if api_key and provider:
            self._data["profiles"][name]["api_keys"][provider] = api_key

        # 첫 프로필이면 현재 프로필로 설정
        if self._data["current_profile"] is None:
            self._data["current_profile"] = name

        return self._save()

    @staticmethod
    def _normalize_default_models(profile: dict) -> dict:
        """[Migration & Fallback Guard] 구버전 프로필의 단일 모델 스키마를 2분할 스키마로 변환한다.

        과거에는 {"provider", "model"} 또는 {"provider", "model_screening", "model_verify"}
        형태로 저장된 경우가 있어, 분리된 키가 없으면 레거시 단일 값을 스크리닝/검증
        양쪽의 Fallback으로 사용한다. 어떤 형태가 와도 4개 키를 모두 갖춘 dict를 반환
        하므로 이후 로직이 KeyError 없이 안전하게 동작한다.
        """
        dm = profile.get("default_models") or {}
        legacy_provider = dm.get("provider", "")
        legacy_screening_model = dm.get("model_screening") or dm.get("model", "")
        legacy_verify_model = dm.get("model_verify") or dm.get("model", "")
        return {
            "screening_provider": dm.get("screening_provider") or legacy_provider,
            "screening_model": dm.get("screening_model") or legacy_screening_model,
            "verify_provider": dm.get("verify_provider") or legacy_provider,
            "verify_model": dm.get("verify_model") or legacy_verify_model,
        }

    def add_api_key(self, profile_name: str, provider: str, api_key: str, password: Optional[str] = None) -> bool:
        """현재 프로필에 특정 프로바이더의 API 키를 .env 파일에 저장하고 런타임에도 즉시 등록합니다."""
        env_path = Path(__file__).parent.parent / ".env"
        success = write_env_keys(env_path, {provider: api_key})
        
        env_mapping = {
            "gemini": "GEMINI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY"
        }
        env_name = env_mapping.get(provider)
        if env_name and success:
            os.environ[env_name] = api_key
            self._current_decrypted_keys[provider] = api_key
            
        return success

    def delete_api_key(self, profile_name: str, provider: str) -> bool:
        """.env 파일 및 런타임 환경변수에서 특정 API 키를 빈 값으로 삭제합니다."""
        env_path = Path(__file__).parent.parent / ".env"
        success = write_env_keys(env_path, {provider: ""})
        
        env_mapping = {
            "gemini": "GEMINI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY"
        }
        env_name = env_mapping.get(provider)
        if env_name and success:
            if env_name in os.environ:
                del os.environ[env_name]
            if provider in self._current_decrypted_keys:
                del self._current_decrypted_keys[provider]
                
        return success

    def login(self, profile_name: str, password: Optional[str] = None) -> Optional[dict]:
        """프로필에 로그인합니다 (비밀번호 검증 없이 즉시 로그인)."""
        self._data = self._load()
        profile = self._data["profiles"].get(profile_name)
        if not profile:
            logger.error("프로필을 찾을 수 없습니다: %s", profile_name)
            return None

        self._data["current_profile"] = profile_name
        self._save()

        # .env 또는 os.environ 에서 API 키 읽어오기
        env_keys = {}
        for prov, env_name in [("gemini", "GEMINI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY")]:
            val = os.getenv(env_name)
            if val:
                env_keys[prov] = val
                
        self._current_decrypted_keys = env_keys

        default_models = self._normalize_default_models(profile)

        return {
            "name": profile_name,
            "api_keys": list(env_keys.keys()),
            "default_models": default_models
        }

    def logout(self) -> None:
        """현재 프로필 로그아웃 (메모리에서 API 키 제거)."""
        # 1. 파일에 현재 프로필 해제 상태를 먼저 안전하게 저장
        self._data["current_profile"] = None
        self._save()
        # 2. 저장 완료 후 메모리 캐시 초기화
        self._current_decrypted_keys = {}
        logger.info("로그아웃 완료.")

    def list_profiles(self) -> list[dict]:
        """프로필 목록을 반환합니다 (비밀 정보 제외)."""
        result = []
        current = self._data.get("current_profile")
        for name, profile in self._data["profiles"].items():
            providers = list(profile.get("api_keys", {}).keys())

            default_models = self._normalize_default_models(profile)

            result.append({
                "name": name,
                "api_keys": providers,
                "default_models": default_models,
                "is_current": (name == current),
                "created_at": profile.get("created_at", ""),
            })
        return result

    def delete_profile(self, name: str) -> bool:
        """프로필을 삭제합니다."""
        if name not in self._data["profiles"]:
            logger.error("프로필을 찾을 수 없습니다: %s", name)
            return False

        del self._data["profiles"][name]

        if self._data["current_profile"] == name:
            self._data["current_profile"] = None
            self._current_decrypted_keys = {}

        return self._save()

    def get_current_profile(self) -> Optional[str]:
        """현재 활성 프로필 이름을 반환합니다."""
        return self._data.get("current_profile")

    def select_model(
        self,
        profile_name: str,
        screening_provider: str,
        screening_model: str,
        verify_provider: str,
        verify_model: str
    ) -> bool:
        """프로필의 디폴트 모델 선택을 업데이트합니다."""
        profile = self._data["profiles"].get(profile_name)
        if not profile:
            logger.error("프로필을 찾을 수 없습니다: %s", profile_name)
            return False

        profile["default_models"] = {
            "screening_provider": screening_provider,
            "screening_model": screening_model,
            "verify_provider": verify_provider,
            "verify_model": verify_model
        }
        return self._save()

    def get_session_data(self) -> Optional[dict]:
        """현재 로그인된 프로필의 세션 데이터를 반환합니다."""
        current = self.get_current_profile()
        if not current:
            return None

        profile = self._data["profiles"].get(current)
        if not profile:
            return None

        default_models = self._normalize_default_models(profile)

        # .env 또는 os.environ 에서 API 키 읽어오기
        env_keys = {}
        for prov, env_name in [("gemini", "GEMINI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY")]:
            val = os.getenv(env_name)
            if val:
                env_keys[prov] = val
                
        self._current_decrypted_keys = env_keys

        return {
            "profile_name": current,
            "api_keys": self._current_decrypted_keys,
            "default_models": default_models
        }


    def interactive_add_profile(self, config: dict) -> Optional[dict]:
        print("대화형 추가는 웹 대시보드(http://localhost:8000)를 사용해 주세요.")
        return None

    def interactive_select_model(self, config: dict) -> bool:
        print("모델 변경은 웹 대시보드를 사용해 주세요.")
        return False
