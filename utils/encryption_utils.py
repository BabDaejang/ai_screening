"""API 키 암호화/복호화 유틸리티 (cryptography.fernet).

사용자가 입력한 LLM API 키를 Fernet(AES-128-CBC + HMAC-SHA256, 인증 암호화)으로
암호화하여 DB(users.encrypted_api_keys)에 저장하고, LLM API 호출 직전에 복호화한다.

마스터 키는 유일하게 환경 변수 ENCRYPTION_KEY 에서만 읽는다:
    - 로컬 개발: .env 의 ENCRYPTION_KEY
    - Vercel 배포: Project Settings → Environment Variables (Secrets)

키 생성 방법 (1회):
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class EncryptionError(Exception):
    """암호화/복호화 실패 (마스터 키 미설정·불일치·토큰 손상)."""


_fernet: Optional[Fernet] = None


def get_fernet() -> Fernet:
    """ENCRYPTION_KEY 환경 변수로부터 Fernet 인스턴스를 생성/캐싱한다."""
    global _fernet
    if _fernet is None:
        key = (os.getenv("ENCRYPTION_KEY") or "").strip()
        if not key:
            raise EncryptionError(
                "ENCRYPTION_KEY 환경 변수가 설정되지 않았습니다. "
                "Fernet.generate_key()로 생성한 키를 .env 또는 Vercel Secrets에 등록하세요."
            )
        try:
            _fernet = Fernet(key.encode("utf-8"))
        except (ValueError, TypeError) as e:
            raise EncryptionError(f"ENCRYPTION_KEY 형식이 올바르지 않습니다 (32바이트 url-safe base64 필요): {e}")
    return _fernet


def encrypt_api_key(plain_key: str) -> str:
    """API 키 평문 → Fernet 암호문(문자열). DB 저장용."""
    if not plain_key:
        return ""
    return get_fernet().encrypt(plain_key.encode("utf-8")).decode("utf-8")


def decrypt_api_key(token: str) -> str:
    """DB에 저장된 Fernet 암호문 → API 키 평문. LLM API 호출 직전에만 사용."""
    if not token:
        return ""
    try:
        return get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise EncryptionError(
            "API 키 복호화 실패: ENCRYPTION_KEY가 변경되었거나 암호문이 손상되었습니다. "
            "설정 화면에서 API 키를 다시 등록해 주세요."
        )


def encrypt_payload(data: bytes) -> str:
    """임의 바이트 페이로드 암호화 (세션 토큰 등 내부 용도)."""
    return get_fernet().encrypt(data).decode("utf-8")


def decrypt_payload(token: str, ttl_seconds: Optional[int] = None) -> bytes:
    """암호문 복호화. ttl_seconds 지정 시 발급 시점 기준 만료를 함께 검증한다."""
    try:
        return get_fernet().decrypt(token.encode("utf-8"), ttl=ttl_seconds)
    except InvalidToken:
        raise EncryptionError("토큰이 유효하지 않거나 만료되었습니다.")
