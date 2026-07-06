"""사용자 계정 관리 모듈 (Supabase DB 기반).

구 버전(~/.ai_screening/profiles.yaml + .env 평문 API 키)을 전면 폐기하고:
- 회원가입/로그인: username + 비밀번호(passlib bcrypt 단방향 해시, users.hashed_password)
- API 키: Fernet(ENCRYPTION_KEY)으로 암호화하여 users.encrypted_api_keys(jsonb)에 저장
- 세션: 무상태 Bearer 토큰 (utils.auth_utils) — 서버리스(Vercel) 호환

이 클래스는 무상태(stateless)다. '현재 로그인 사용자'라는 전역 개념은 없으며,
호출부(FastAPI 의존성/CLI)가 토큰으로 식별한 사용자 행(dict)을 넘겨 사용한다.
"""

from __future__ import annotations

import logging
from typing import Optional

from database import DatabaseError, db_delete, db_insert, db_select_one, db_update
from utils.auth_utils import (
    create_access_token,
    decode_access_token,
    hash_password,
    validate_credentials_format,
    verify_password,
)
from utils.encryption_utils import EncryptionError, decrypt_api_key, encrypt_api_key

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("gemini", "anthropic", "openai")


class UserManager:
    """DB 기반 사용자 계정/API 키/기본 모델 관리."""

    # ---------------------------------------------------------
    # 회원가입 / 로그인
    # ---------------------------------------------------------
    def register(self, username: str, password: str) -> dict:
        """회원가입. 성공 시 공개 사용자 정보 dict 반환, 실패 시 ValueError(사유)."""
        username = (username or "").strip()
        reason = validate_credentials_format(username, password)
        if reason:
            raise ValueError(reason)

        if db_select_one("users", {"username": username}, columns="id"):
            raise ValueError(f"이미 존재하는 사용자 ID입니다: {username}")

        row = db_insert("users", {
            "username": username,
            "hashed_password": hash_password(password),
            "encrypted_api_keys": {},
            "default_models": {},
        })
        logger.info("신규 사용자 가입: %s", username)
        return {"user_id": row["id"], "username": row["username"]}

    def authenticate(self, username: str, password: str) -> Optional[dict]:
        """비밀번호 검증. 성공 시 사용자 행(dict), 실패 시 None."""
        user = db_select_one("users", {"username": (username or "").strip()})
        if not user:
            return None
        if not verify_password(password, user.get("hashed_password", "")):
            return None
        return user

    def login(self, username: str, password: str) -> Optional[dict]:
        """로그인. 성공 시 세션 토큰 + 프로필 요약 반환, 실패 시 None."""
        user = self.authenticate(username, password)
        if not user:
            logger.warning("로그인 실패: %s", username)
            return None
        token = create_access_token(user["id"], user["username"])
        return {
            "token": token,
            "name": user["username"],
            "user_id": user["id"],
            "api_keys": list((user.get("encrypted_api_keys") or {}).keys()),
            "default_models": self._normalize_default_models(user),
        }

    def get_user_by_token(self, token: str) -> Optional[dict]:
        """Bearer 토큰 → 사용자 행(dict). 위조/만료/삭제된 계정이면 None."""
        payload = decode_access_token(token)
        if not payload:
            return None
        try:
            return db_select_one("users", {"id": payload["uid"]})
        except DatabaseError as e:
            logger.error("토큰 사용자 조회 실패: %s", e)
            return None

    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        return db_select_one("users", {"id": user_id})

    def delete_user(self, user_id: str) -> bool:
        """계정 삭제 (프로젝트/체크포인트는 FK cascade로 함께 삭제)."""
        return bool(db_delete("users", {"id": user_id}))

    # ---------------------------------------------------------
    # API 키 (Fernet 암호화 저장)
    # ---------------------------------------------------------
    def set_api_key(self, user: dict, provider: str, api_key: str) -> bool:
        """사용자 API 키를 암호화하여 DB에 저장한다 (.env 저장 방식 폐기)."""
        if provider not in SUPPORTED_PROVIDERS:
            logger.error("지원하지 않는 프로바이더: %s", provider)
            return False
        keys = dict(user.get("encrypted_api_keys") or {})
        keys[provider] = encrypt_api_key(api_key.strip())
        db_update("users", {"id": user["id"]}, {"encrypted_api_keys": keys})
        user["encrypted_api_keys"] = keys  # 호출부가 들고 있는 행도 동기화
        return True

    def delete_api_key(self, user: dict, provider: str) -> bool:
        keys = dict(user.get("encrypted_api_keys") or {})
        if provider not in keys:
            return False
        del keys[provider]
        db_update("users", {"id": user["id"]}, {"encrypted_api_keys": keys})
        user["encrypted_api_keys"] = keys
        return True

    def get_decrypted_api_key(self, user: dict, provider: str) -> Optional[str]:
        """LLM API 호출 직전에만 사용: 해당 프로바이더 키를 복호화하여 반환."""
        token = (user.get("encrypted_api_keys") or {}).get(provider)
        if not token:
            return None
        return decrypt_api_key(token)

    def get_decrypted_api_keys(self, user: dict) -> dict:
        """등록된 모든 키를 복호화한 {provider: plain_key} dict.

        일부 키가 복호화 불가(마스터 키 교체 등)여도 나머지 키는 정상 반환한다.
        """
        result: dict[str, str] = {}
        for provider, token in (user.get("encrypted_api_keys") or {}).items():
            try:
                plain = decrypt_api_key(token)
                if plain:
                    result[provider] = plain
            except EncryptionError as e:
                logger.error("'%s' API 키 복호화 실패 (재등록 필요): %s", provider, e)
        return result

    # ---------------------------------------------------------
    # 기본 모델 설정
    # ---------------------------------------------------------
    @staticmethod
    def _normalize_default_models(user: dict) -> dict:
        """어떤 형태로 저장돼 있어도 4개 키를 모두 갖춘 dict를 보장한다 (KeyError 방지)."""
        dm = user.get("default_models") or {}
        legacy_provider = dm.get("provider", "")
        legacy_screening = dm.get("model_screening") or dm.get("model", "")
        legacy_verify = dm.get("model_verify") or dm.get("model", "")
        return {
            "screening_provider": dm.get("screening_provider") or legacy_provider,
            "screening_model": dm.get("screening_model") or legacy_screening,
            "verify_provider": dm.get("verify_provider") or legacy_provider,
            "verify_model": dm.get("verify_model") or legacy_verify,
        }

    def select_model(self, user: dict, screening_provider: str, screening_model: str,
                     verify_provider: str, verify_model: str) -> bool:
        default_models = {
            "screening_provider": screening_provider,
            "screening_model": screening_model,
            "verify_provider": verify_provider,
            "verify_model": verify_model,
        }
        db_update("users", {"id": user["id"]}, {"default_models": default_models})
        user["default_models"] = default_models
        return True

    # ---------------------------------------------------------
    # 파이프라인용 세션 데이터
    # ---------------------------------------------------------
    def get_session_data(self, user: dict) -> dict:
        """분석 파이프라인/CLI에 넘길 세션 데이터 (API 키는 복호화된 평문 dict)."""
        return {
            "profile_name": user["username"],
            "user_id": user["id"],
            "api_keys": self.get_decrypted_api_keys(user),
            "default_models": self._normalize_default_models(user),
        }

    def get_public_profile(self, user: dict) -> dict:
        """UI 표시용 공개 프로필 (키 원문/암호문 미포함)."""
        return {
            "name": user["username"],
            "user_id": user["id"],
            "api_keys": list((user.get("encrypted_api_keys") or {}).keys()),
            "default_models": self._normalize_default_models(user),
            "created_at": user.get("created_at", ""),
        }
