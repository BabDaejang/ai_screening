"""비밀번호 해시/검증 및 로그인 세션 토큰 유틸리티.

- 비밀번호: passlib + bcrypt 단방향 해시. 평문은 어디에도 저장하지 않는다.
- 세션 토큰: 로그인 성공 시 발급하는 무상태(stateless) 토큰.
  {user_id, username}을 Fernet(ENCRYPTION_KEY)으로 인증 암호화하며,
  Fernet 내장 타임스탬프로 만료(TTL)를 검증하므로 서버에 세션 저장소가 필요 없다
  (Vercel 서버리스의 무상태 제약에 부합).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from passlib.context import CryptContext

from utils.encryption_utils import EncryptionError, decrypt_payload, encrypt_payload

logger = logging.getLogger(__name__)

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 로그인 세션 토큰 유효기간 (기본 12시간, 환경 변수로 재정의 가능)
TOKEN_TTL_SECONDS = int(os.getenv("AUTH_TOKEN_TTL_SECONDS", str(12 * 3600)))


# -------------------------------------------------------------
# 비밀번호 해시 (passlib + bcrypt)
# -------------------------------------------------------------
def hash_password(plain_password: str) -> str:
    """비밀번호 → bcrypt 해시 (DB users.hashed_password 저장용)."""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """로그인 시 비밀번호 검증. 해시 손상 등 어떤 경우에도 예외 대신 False."""
    if not plain_password or not hashed_password:
        return False
    try:
        return _pwd_context.verify(plain_password, hashed_password)
    except (ValueError, TypeError) as e:
        logger.warning("비밀번호 해시 검증 오류: %s", e)
        return False


def validate_credentials_format(username: str, password: str) -> Optional[str]:
    """가입 입력값 형식 검증. 문제가 있으면 사용자에게 보여줄 사유 문자열을 반환."""
    if not username or len(username.strip()) < 2:
        return "사용자 ID는 2자 이상이어야 합니다."
    if len(username.strip()) > 64:
        return "사용자 ID는 64자 이하여야 합니다."
    if not password or len(password) < 8:
        return "비밀번호는 8자 이상이어야 합니다."
    return None


# -------------------------------------------------------------
# 로그인 세션 토큰 (Fernet 기반, 무상태)
# -------------------------------------------------------------
def create_access_token(user_id: str, username: str) -> str:
    """로그인 성공 시 발급. 클라이언트는 Authorization: Bearer <token>으로 제출한다."""
    payload = json.dumps({"uid": str(user_id), "un": username}).encode("utf-8")
    return encrypt_payload(payload)


def decode_access_token(token: str) -> Optional[dict]:
    """토큰 → {"uid": ..., "un": ...}. 위조·만료 시 None."""
    if not token:
        return None
    try:
        raw = decrypt_payload(token, ttl_seconds=TOKEN_TTL_SECONDS)
        data = json.loads(raw.decode("utf-8"))
    except (EncryptionError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("uid"):
        return None
    return data
