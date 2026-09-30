"""认证与密码安全。

不引入额外依赖：密码哈希用标准库 PBKDF2-HMAC-SHA256，令牌用 HMAC 签名的自包含结构。
- 密码加盐哈希，永不明文落库。
- 令牌带过期时间与签名，篡改后校验必然失败。
- 校验用 compare_digest 做常数时间比较。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from app.core.config import settings

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO}${_b64e(salt)}${_b64e(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_b64, hash_b64 = stored.split("$")
        if algo != _ALGO:
            return False
        salt, expected = _b64d(salt_b64), _b64d(hash_b64)
    except (ValueError, TypeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return hmac.compare_digest(dk, expected)


def password_issue(password: str) -> str:
    """不满足要求时返回原因，满足返回空串。"""
    if not password or len(password) < 8:
        return "密码至少 8 位"
    if len(password) > 128:
        return "密码最多 128 位"
    return ""


def make_token(user_id: int, role: str) -> tuple[str, int]:
    exp = int(time.time()) + settings.token_ttl_hours * 3600
    payload = {"u": user_id, "r": role, "e": exp, "n": secrets.token_hex(4)}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_b64e(_sign(body))}", exp


def parse_token(token: str) -> dict[str, Any] | None:
    """签名不对、格式不对、已过期都返回 None。"""
    try:
        body, sig_b64 = token.split(".")
        if not hmac.compare_digest(_sign(body), _b64d(sig_b64)):
            return None
        payload = json.loads(_b64d(body).decode("utf-8"))
        if int(payload.get("e", 0)) < int(time.time()):
            return None
        return payload
    except Exception:  # noqa: BLE001
        return None


def _sign(body: str) -> bytes:
    return hmac.new(settings.secret_key.encode("utf-8"), body.encode("ascii"),
                    hashlib.sha256).digest()


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
