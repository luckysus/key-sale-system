import base64
from collections import defaultdict, deque
import hashlib
import hmac
import logging
import os
import secrets
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

from cryptography.fernet import Fernet, MultiFernet


logger = logging.getLogger("backend.security")
MIN_SECRET_LENGTH = 32


def now_ts() -> int:
    import time

    return int(time.time())


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    if not password:
        raise ValueError("password required")
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return "pbkdf2_sha256$200000$%s$%s" % (
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        alg, rounds, salt_b64, digest_b64 = stored.split("$", 3)
        if alg != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def token() -> str:
    return secrets.token_urlsafe(32)


def _enforce_secret_permissions(path: Path) -> None:
    # Windows 的 ACL 与 POSIX 权限位不同，chmod 在此意义有限，跳过以避免误导。
    if os.name == "nt":
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        logger.warning("无法将密钥文件权限收紧为 600，请手动检查: %s", path)


def load_or_create_secret(path: Path) -> str:
    env_secret = os.environ.get("APP_SECRET")
    if env_secret:
        if len(env_secret) < MIN_SECRET_LENGTH:
            logger.warning("APP_SECRET 长度不足 %d 字符，安全性较弱，建议使用更强的随机密钥", MIN_SECRET_LENGTH)
        return env_secret
    if path.exists():
        # 对已存在的密钥文件保持内容兼容，仅强制收紧文件权限。
        _enforce_secret_permissions(path)
        value = path.read_text(encoding="utf-8").strip()
        if len(value) < MIN_SECRET_LENGTH:
            logger.warning("密钥文件内容过短，安全性不足，建议重新生成: %s", path)
        return value
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(48)
    path.write_text(value, encoding="utf-8")
    _enforce_secret_permissions(path)
    return value


def parse_trusted_proxies(raw: str) -> set[str]:
    return {item.strip() for item in (raw or "").split(",") if item.strip()}


def resolve_client_ip(direct_ip: str, forwarded_for: str, trusted_proxies: Iterable[str]) -> str:
    """根据可信代理列表安全地解析真实客户端 IP。

    - 仅当直连来源(direct_ip)属于可信代理时，才采信 X-Forwarded-For；
    - 采信时从最右侧(最接近可信边界)向左取第一个非可信 IP，避免伪造头绕过限流；
    - 其余情况一律使用直连 IP。
    """
    direct = (direct_ip or "").strip()
    trusted = set(trusted_proxies or ())
    if not trusted or direct not in trusted:
        return direct or "unknown"
    chain = [item.strip() for item in (forwarded_for or "").split(",") if item.strip()]
    for candidate in reversed(chain):
        if candidate not in trusted:
            return candidate
    return direct or "unknown"


# Fernet 密钥派生：新数据用 PBKDF2-HMAC-SHA256 派生的密钥加密；
# 旧数据可能用历史的 SHA256 单轮派生密钥加密，需保留以向后兼容解密。
_FERNET_PBKDF2_SALT = b"ldxp_fernet_salt_v1"
_FERNET_PBKDF2_ROUNDS = 100_000


def _fernet_key_pbkdf2(secret: str) -> bytes:
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), _FERNET_PBKDF2_SALT, _FERNET_PBKDF2_ROUNDS)
    return base64.urlsafe_b64encode(digest)


def _fernet_key_legacy_sha256(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def fernet_from_secret(secret: str) -> MultiFernet:
    """返回 MultiFernet：加密统一使用列表首位(PBKDF2)密钥；
    解密时按顺序尝试各密钥，因此旧 SHA256 密钥加密的历史数据仍可解密。
    """
    return MultiFernet(
        [
            Fernet(_fernet_key_pbkdf2(secret)),
            Fernet(_fernet_key_legacy_sha256(secret)),
        ]
    )


def same_origin_allowed(host: str, origin: str = "", referer: str = "") -> bool:
    expected = (host or "").split(",", 1)[0].strip().lower()
    if not expected:
        return False
    source = origin or referer
    if not source:
        return True
    parsed = urlparse(source)
    return (parsed.netloc or "").lower() == expected


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[int]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: int, now: Optional[int] = None) -> bool:
        current = now_ts() if now is None else int(now)
        bucket = self._hits[key]
        cutoff = current - int(window_seconds)
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= int(limit):
            return False
        bucket.append(current)
        return True
