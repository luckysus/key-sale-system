import asyncio
import hashlib
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Optional
from urllib.parse import unquote, urlparse

import httpx
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .converter import build_accounts_zip, safe_zip_name
from .db import (
    allocated_ids,
    authenticate,
    bulk_delete_access_logs,
    bulk_delete_batches,
    bulk_set_card_status,
    card_counts,
    cleanup_security_state,
    clear_login_failures,
    connect,
    create_batch,
    create_cards,
    delete_batch,
    create_session,
    delete_session,
    ensure_admin,
    get_card,
    get_session_user,
    get_setting,
    init_db,
    list_account_allocations,
    list_access_logs,
    list_admin_audit_logs,
    list_batches,
    list_cards,
    list_login_failures,
    log_access,
    log_admin_audit,
    manual_extracted_accounts,
    mark_card_used,
    put_setting,
    record_login_failure,
    rowdict,
    set_account_extracted,
    set_card_status,
    is_login_locked,
)
from .notifier import send_smtp
from .redeem_guard import (
    RedeemCardBusy,
    RedeemGuard,
    RedeemGuardUnavailable,
    RedeemRateLimited,
    RedeemServerBusy,
    validate_lease_seconds,
)
from .security import (
    RateLimiter,
    fernet_from_secret,
    hash_password,
    load_or_create_secret,
    now_ts,
    parse_trusted_proxies,
    resolve_client_ip,
    same_origin_allowed,
    verify_password,
)
from .sub2api_client import Sub2APIClient, Sub2APISettings


ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger("backend.main")
DATA_DIR = ROOT / "data"
DB_PATH = Path(os.environ.get("DB_PATH", DATA_DIR / "sale.sqlite"))
STATIC_DIR = ROOT / "frontend" / "dist"
ADMIN_STATIC_DIR = STATIC_DIR / "admin"
BUYER_STATIC_DIR = STATIC_DIR / "buyer"
SECRET = load_or_create_secret(DATA_DIR / "app-secret.txt")
FERNET = fernet_from_secret(SECRET)
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") != "0"
SESSION_COOKIE = "ks_session"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "x-csrf-token"
# 登录接口本身负责下发 csrf cookie，故免于 CSRF 校验（仍保留同源校验）。
CSRF_EXEMPT_PATHS = {"/api/admin/login"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
ENABLE_API_DOCS = os.environ.get("ENABLE_API_DOCS", "").strip().lower() in {"1", "true", "yes", "on"}
TRUSTED_PROXIES = parse_trusted_proxies(os.environ.get("TRUSTED_PROXIES", ""))
LOGIN_LOCK_ATTEMPTS = int(os.environ.get("LOGIN_LOCK_ATTEMPTS", "5"))
LOGIN_LOCK_SECONDS = int(os.environ.get("LOGIN_LOCK_SECONDS", "900"))
REDEEM_MAX_BODY_BYTES = int(os.environ.get("REDEEM_MAX_BODY_BYTES", "2048"))
GENERIC_CARD_ERROR = "卡密无效或不可用"
# sub2api 目标主机白名单（SSRF 防护）：默认锁定本机，可经环境变量扩展。
ALLOWED_SUB2API_HOSTS = {
    item.strip().lower()
    for item in os.environ.get("ALLOWED_SUB2API_HOSTS", "127.0.0.1,localhost").split(",")
    if item.strip()
}
ALLOWED_HOSTS = {
    item.strip().lower()
    for item in os.environ.get("ALLOWED_HOSTS", "admin.example.com,buyer.example.com,localhost,127.0.0.1").split(",")
    if item.strip()
}
ADMIN_HOSTS = {
    item.strip().lower()
    for item in os.environ.get("ADMIN_HOSTS", "admin.example.com").split(",")
    if item.strip()
}
BUYER_HOSTS = {
    item.strip().lower()
    for item in os.environ.get("BUYER_HOSTS", "buyer.example.com").split(",")
    if item.strip()
}
RATE_LIMITER = RateLimiter()
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
REDEEM_PREPARE_TIMEOUT_SECONDS = int(os.environ.get("REDEEM_PREPARE_TIMEOUT_SECONDS", "180"))
REDEEM_CONCURRENCY = int(os.environ.get("REDEEM_CONCURRENCY", "10"))
REDEEM_LEASE_SECONDS = validate_lease_seconds(
    int(os.environ.get("REDEEM_LEASE_SECONDS", "210")),
    REDEEM_PREPARE_TIMEOUT_SECONDS,
)
REDEEM_GUARD = RedeemGuard.from_url(
    REDIS_URL,
    ip_limit=int(os.environ.get("REDEEM_IP_LIMIT", "20")),
    ip_window_seconds=int(os.environ.get("REDEEM_IP_WINDOW_SECONDS", "60")),
    card_limit=int(os.environ.get("REDEEM_CARD_LIMIT", "5")),
    card_window_seconds=int(os.environ.get("REDEEM_CARD_WINDOW_SECONDS", "300")),
    failure_threshold=int(os.environ.get("REDEEM_FAILURE_THRESHOLD", "5")),
    failure_window_seconds=int(os.environ.get("REDEEM_FAILURE_WINDOW_SECONDS", "600")),
    concurrency=REDEEM_CONCURRENCY,
    lease_seconds=REDEEM_LEASE_SECONDS,
)
CARD_CODE_RE = re.compile(r"^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}(?:-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}){3}$")
SENSITIVE_PATH_PREFIXES = (
    ".",
    "api/",
    "backend/",
    "data/",
    "deploy/",
    "frontend/",
    "node_modules/",
    "public/",
    "tests/",
    "__pycache__/",
    "wp-admin/",
    "wp-content/",
    "wp-includes/",
    "wp-json/",
    "wp-login.php",
)
SENSITIVE_PATH_SUFFIXES = (
    ".bak",
    ".db",
    ".egg-info",
    ".env",
    ".ini",
    ".key",
    ".lock",
    ".log",
    ".map",
    ".mjs",
    ".pem",
    ".py",
    ".pyc",
    ".pyo",
    ".pyw",
    ".sqlite",
    ".sql",
    ".toml",
    ".ts",
    ".txt",
    ".vue",
    ".yaml",
    ".yml",
)

app = FastAPI(
    title="Key Sale System",
    docs_url="/docs" if ENABLE_API_DOCS else None,
    redoc_url="/redoc" if ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_API_DOCS else None,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(ALLOWED_HOSTS))


if not ENABLE_API_DOCS:
    # 默认关闭自动文档：显式返回 404，避免被 SPA 回退路由捕获而返回首页。
    def _docs_disabled():
        raise HTTPException(status_code=404, detail="Not Found")

    for _doc_path in ("/docs", "/redoc", "/openapi.json"):
        app.add_api_route(_doc_path, _docs_disabled, methods=["GET"], include_in_schema=False)


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)
    turnstile_token: str = Field(default="", max_length=2048)


class ProfileBody(BaseModel):
    email: str = Field(default="", max_length=120)
    # avatar 允许存储 base64 内联图片（前端已限制在 200KB 以内）。
    avatar: str = Field(default="", max_length=300000)

    @field_validator("avatar")
    @classmethod
    def _validate_avatar(cls, value: str) -> str:
        # 为空放行；非空时必须是白名单内的 data URI 图片（与前端契约一致）。
        if not value:
            return value
        allowed_prefixes = (
            "data:image/png;",
            "data:image/jpeg;",
            "data:image/webp;",
            "data:image/gif;",
        )
        if not value.startswith(allowed_prefixes):
            raise ValueError("头像格式不受支持，仅允许 png/jpeg/webp/gif 的 data URI 图片")
        return value


class PasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class Sub2APISettingsBody(BaseModel):
    base_url: str = Field(default="http://127.0.0.1:5220", max_length=500)
    api_key: str = Field(default="", max_length=500)
    bearer_token: str = Field(default="", max_length=1000)


class TurnstileSettingsBody(BaseModel):
    enabled: bool = False
    site_key: str = Field(default="", max_length=500)
    secret_key: str = Field(default="", max_length=500)


class GenerateCardsBody(BaseModel):
    batch_id: Optional[int] = None
    batch_name: str = ""
    batch_note: str = ""
    group_id: str
    group_name: str
    account_count: int = Field(ge=1, le=200)
    generate_count: int = Field(ge=1, le=500)
    days: int = Field(default=0, ge=0, le=3650)
    points: int = Field(default=0, ge=0)


class StatusBody(BaseModel):
    status: str = Field(max_length=20)


class AccountExtractionStatusBody(BaseModel):
    extracted: bool
    account_name: str = Field(default="", max_length=300)


class BulkDeleteBody(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=500)


class BulkStatusBody(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=500)
    status: str = Field(max_length=20)


class StockThreshold(BaseModel):
    group_id: str = Field(min_length=1, max_length=120)
    group_name: str = Field(default="", max_length=200)
    min_available: int = Field(ge=0, le=100000)
    enabled: bool = True


class StockThresholdsBody(BaseModel):
    thresholds: list[StockThreshold] = Field(default_factory=list, max_length=500)


class SMTPSettingsBody(BaseModel):
    enabled: bool = False
    host: str = Field(default="", max_length=300)
    port: int = Field(default=465, ge=1, le=65535)
    username: str = Field(default="", max_length=300)
    password: str = Field(default="", max_length=500)
    from_email: str = Field(default="", max_length=300)
    to_email: str = Field(default="", max_length=300)
    use_ssl: bool = True
    use_tls: bool = False


class RedeemBody(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    user: str = Field(default="", max_length=120)
    turnstile_token: str = Field(default="", max_length=2048)


class InsufficientAccountsError(ValueError):
    pass


def db():
    conn = connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def client_ip(request: Request) -> str:
    direct = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for", "")
    value = resolve_client_ip(direct, forwarded, TRUSTED_PROXIES)
    return (value or "unknown")[:64]


def request_host(request: Request) -> str:
    raw = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    raw = raw.split(",", 1)[0].strip().lower()
    return raw.rsplit(":", 1)[0] if ":" in raw else raw


def record_audit(conn, request: Request, action: str, *, actor: Optional[dict] = None, target: str = "", result: str = "ok") -> None:
    # 审计记录属于旁路，不得因异常影响业务主流程。
    try:
        log_admin_audit(
            conn,
            actor_id=(actor or {}).get("id"),
            actor_username=(actor or {}).get("username", ""),
            action=action,
            target=target,
            ip=client_ip(request),
            result=result,
        )
    except Exception:
        logger.exception("admin audit log write failed: action=%s", action)


def check_rate(key: str, limit: int, window_seconds: int) -> None:
    if not RATE_LIMITER.allow(key, limit, window_seconds):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")


def redeem_guard_http_error(error: Exception) -> HTTPException:
    if isinstance(error, RedeemRateLimited):
        return HTTPException(
            status_code=429,
            detail=str(error),
            headers={"Retry-After": str(error.retry_after)},
        )
    if isinstance(error, RedeemCardBusy):
        return HTTPException(status_code=409, detail=str(error), headers={"Retry-After": "5"})
    if isinstance(error, RedeemServerBusy):
        return HTTPException(status_code=503, detail=str(error), headers={"Retry-After": "15"})
    return HTTPException(status_code=503, detail="兑换安全服务暂时不可用", headers={"Retry-After": "30"})


async def record_buyer_redeem_failure(ip: str) -> None:
    try:
        await REDEEM_GUARD.record_failure(ip)
    except RedeemGuardUnavailable as exc:
        raise redeem_guard_http_error(exc) from exc


def issue_csrf_cookie(response: Response) -> str:
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=COOKIE_SECURE,
        samesite="strict",
        max_age=604800,
        path="/",
    )
    return csrf_token


def clean_base_url(value: str) -> str:
    url = (value or "").strip().rstrip("/") or "http://127.0.0.1:5220"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="sub2api 地址必须是 http/https URL")
    # SSRF 防护：仅允许白名单内的主机，默认锁定本机。
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_SUB2API_HOSTS:
        raise HTTPException(
            status_code=400,
            detail="sub2api 地址主机不在允许列表内，需管理员通过 ALLOWED_SUB2API_HOSTS 配置白名单",
        )
    return url


def safe_log_value(value: str) -> str:
    clean = (value or "").strip()
    digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def is_sensitive_spa_path(path: str) -> bool:
    clean = unquote(path or "").lstrip("/").replace("\\", "/").lower()
    while "//" in clean:
        clean = clean.replace("//", "/")
    if not clean:
        return False
    return clean.startswith(SENSITIVE_PATH_PREFIXES) or clean.endswith(SENSITIVE_PATH_SUFFIXES)


def apply_security_headers(response: Response, request: Request) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' https://challenges.cloudflare.com; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self' data:; connect-src 'self' https://challenges.cloudflare.com; "
        "frame-src https://challenges.cloudflare.com; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    )
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.middleware("http")
async def security_headers_and_csrf(request: Request, call_next):
    host = request_host(request)
    if host in BUYER_HOSTS and (
        request.url.path.startswith("/api/admin/") or request.url.path.startswith("/admin-static/")
    ):
        return apply_security_headers(JSONResponse({"detail": "Not Found"}, status_code=404), request)
    if host in ADMIN_HOSTS and (
        request.url.path in {"/api/redeem", "/api/public/redeem-settings"}
        or request.url.path.startswith("/buyer-static/")
    ):
        return apply_security_headers(JSONResponse({"detail": "Not Found"}, status_code=404), request)
    if request.method == "POST" and request.url.path == "/api/redeem":
        try:
            content_length = int(request.headers.get("content-length") or "0")
        except ValueError:
            return apply_security_headers(JSONResponse({"detail": "请求体大小无效"}, status_code=400), request)
        if content_length > REDEEM_MAX_BODY_BYTES:
            return apply_security_headers(JSONResponse({"detail": "请求体过大"}, status_code=413), request)

    if request.method in WRITE_METHODS and request.url.path.startswith("/api/admin/"):
        origin_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        fetch_site = request.headers.get("sec-fetch-site", "").lower()
        # 纵深防御：保留同源校验。
        if fetch_site == "cross-site" or not same_origin_allowed(origin_host, request.headers.get("origin", ""), request.headers.get("referer", "")):
            return apply_security_headers(JSONResponse({"detail": "跨站请求被拒绝"}, status_code=403), request)
        # 显式双提交 Cookie Token：比较请求头与 cookie 中的 csrf_token（常量时间比较）。
        if request.url.path not in CSRF_EXEMPT_PATHS:
            header_token = request.headers.get(CSRF_HEADER, "")
            cookie_token = request.cookies.get(CSRF_COOKIE, "")
            if not header_token or not cookie_token or not secrets.compare_digest(header_token, cookie_token):
                return apply_security_headers(JSONResponse({"detail": "CSRF 校验失败"}, status_code=403), request)

    response = await call_next(request)
    return apply_security_headers(response, request)


def setup_runtime() -> None:
    conn = connect(DB_PATH)
    try:
        init_db(conn)
        cleanup_security_state(conn)
        username = os.environ.get("ADMIN_USERNAME", "admin")
        env_password = os.environ.get("ADMIN_PASSWORD")
        # 优先使用环境变量口令；此路径不落盘明文密码。
        password = env_password or ("KS_" + secrets.token_urlsafe(18))
        created = ensure_admin(conn, username, password)
        if created and not env_password:
            # 未提供 ADMIN_PASSWORD：只能落盘随机口令供首次登录，权限尽量收紧。
            init_path = DATA_DIR / "admin-init.txt"
            init_path.write_text(f"username={username}\npassword={password}\n", encoding="utf-8")
            try:
                os.chmod(init_path, 0o600)
            except OSError:
                pass
            logger.warning(
                "已生成随机管理员初始口令并写入 %s，生产环境建议改用 ADMIN_PASSWORD 环境变量注入口令，避免明文落盘",
                init_path,
            )
    finally:
        conn.close()


setup_runtime()


def encrypt(value: str) -> str:
    return FERNET.encrypt(value.encode("utf-8")).decode("ascii") if value else ""


def decrypt(value: str) -> str:
    return FERNET.decrypt(value.encode("ascii")).decode("utf-8") if value else ""


def sub2api_settings_from_db(conn) -> Sub2APISettings:
    raw = get_setting(conn, "sub2api") or {}
    base_url = raw.get("base_url") or os.environ.get("SUB2API_BASE_URL") or "http://127.0.0.1:5220"
    return Sub2APISettings(
        base_url=base_url,
        api_key=decrypt(raw.get("api_key_enc", "")) or os.environ.get("SUB2API_API_KEY", ""),
        bearer_token=decrypt(raw.get("bearer_token_enc", "")) or os.environ.get("SUB2API_BEARER_TOKEN", ""),
    )


def account_match_keys(account: dict) -> set[str]:
    creds = account.get("credentials") if isinstance(account.get("credentials"), dict) else {}
    extra = account.get("extra") if isinstance(account.get("extra"), dict) else {}
    values = (
        account.get("name"),
        account.get("email"),
        account.get("account_id"),
        creds.get("email"),
        creds.get("account_id"),
        creds.get("chatgpt_account_id"),
        extra.get("email"),
        extra.get("chatgpt_account_id"),
    )
    return {str(value) for value in values if value not in (None, "")}


def exported_accounts_for(live_accounts: list[dict], exported_accounts: list[dict]) -> list[dict]:
    exported_by_key = {}
    for account in exported_accounts:
        for key in account_match_keys(account):
            exported_by_key.setdefault(key, account)

    selected = []
    for account in live_accounts:
        match = next((exported_by_key[key] for key in account_match_keys(account) if key in exported_by_key), None)
        if not match:
            raise ValueError(f"无法导出完整账号：{account.get('name') or account.get('id') or 'unknown'}")
        selected.append(match)
    return selected


def turnstile_raw(conn) -> dict:
    return get_setting(conn, "turnstile") or {}


def turnstile_secret(conn) -> str:
    raw = turnstile_raw(conn)
    return decrypt(raw.get("secret_key_enc", "")) or os.environ.get("TURNSTILE_SECRET_KEY", "")


def turnstile_site_key(conn) -> str:
    raw = turnstile_raw(conn)
    return raw.get("site_key") or os.environ.get("TURNSTILE_SITE_KEY", "")


def turnstile_public_settings(conn) -> dict:
    raw = turnstile_raw(conn)
    site_key = turnstile_site_key(conn)
    secret_key = turnstile_secret(conn)
    enabled = bool(raw["enabled"]) if "enabled" in raw else os.environ.get("TURNSTILE_ENABLED", "").lower() in {"1", "true", "yes", "on"}
    return {"enabled": bool(enabled and site_key and secret_key), "site_key": site_key}


def verify_turnstile_token(
    conn,
    token_value: str,
    ip: str,
    *,
    required: bool = False,
    expected_hostname: str = "",
    expected_action: str = "",
) -> None:
    settings = turnstile_public_settings(conn)
    if not required and not settings["enabled"]:
        return
    secret_key = turnstile_secret(conn)
    if not settings["site_key"] or not secret_key:
        raise HTTPException(status_code=503, detail="人机验证尚未配置，请联系管理员")
    failure_status = 403 if required else 400
    token_clean = (token_value or "").strip()
    if not token_clean:
        raise HTTPException(status_code=failure_status, detail="请先完成人机验证")
    try:
        response = httpx.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret_key, "response": token_clean, "remoteip": ip},
            timeout=10,
        )
        payload = response.json()
    except Exception:
        raise HTTPException(status_code=failure_status, detail="人机验证暂时不可用，请稍后再试")
    if (
        response.status_code >= 400
        or not payload.get("success")
        or str(payload.get("hostname") or "").lower() != expected_hostname.lower()
        or payload.get("action") != expected_action
    ):
        raise HTTPException(status_code=failure_status, detail="人机验证失败，请重试")


def public_smtp_settings(conn) -> dict:
    raw = get_setting(conn, "smtp") or {}
    return {
        "enabled": bool(raw.get("enabled")),
        "host": raw.get("host", ""),
        "port": int(raw.get("port") or 465),
        "username": raw.get("username", ""),
        "from_email": raw.get("from_email", ""),
        "to_email": raw.get("to_email", ""),
        "use_ssl": bool(raw.get("use_ssl", True)),
        "use_tls": bool(raw.get("use_tls", False)),
        "has_password": bool(raw.get("password_enc")),
    }


def private_smtp_settings(conn) -> dict:
    raw = get_setting(conn, "smtp") or {}
    public = public_smtp_settings(conn)
    return {**public, "password": decrypt(raw.get("password_enc", ""))}


def try_notify(conn, event_key: str, subject: str, body: str) -> bool:
    settings = private_smtp_settings(conn)
    if not settings.get("enabled"):
        return False
    cooldown = get_setting(conn, "notification_cooldown") or {}
    ts = now_ts()
    if ts - int(cooldown.get(event_key, 0) or 0) < 21600:
        return False
    try:
        send_smtp(settings, subject, body)
    except Exception as exc:
        logger.warning("notification failed for %s: %s", event_key, exc)
        return False
    cooldown[event_key] = ts
    put_setting(conn, "notification_cooldown", cooldown)
    return True


def maybe_notify_redeem_abnormal(conn, ip: str) -> None:
    since = now_ts() - 1800
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM card_access_logs WHERE ip = ? AND result != 'success' AND created_at >= ?",
        (ip, since),
    ).fetchone()
    if row and int(row["count"] or 0) >= 8:
        try_notify(conn, f"abnormal_redeem:{ip}", "卡密提取异常提醒", f"IP {ip} 30 分钟内提取失败次数达到 {row['count']} 次。")


def trend_date(ts: int) -> str:
    return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")


def dashboard_payload(conn) -> dict:
    ts = now_ts()
    today_start = int(datetime.fromtimestamp(ts).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    overview = card_counts(conn)
    today_rows = conn.execute(
        """
        SELECT result, COUNT(*) AS count
        FROM card_access_logs
        WHERE created_at >= ?
        GROUP BY result
        """,
        (today_start,),
    ).fetchall()
    overview["today_success"] = sum(int(row["count"] or 0) for row in today_rows if row["result"] == "success")
    overview["today_failed"] = sum(int(row["count"] or 0) for row in today_rows if row["result"] != "success")

    start_date = datetime.fromtimestamp(ts).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=29)
    trend = {
        (start_date + timedelta(days=offset)).strftime("%Y-%m-%d"): {"date": (start_date + timedelta(days=offset)).strftime("%Y-%m-%d"), "success": 0, "failed": 0}
        for offset in range(30)
    }
    rows = conn.execute(
        "SELECT result, created_at FROM card_access_logs WHERE created_at >= ?",
        (int(start_date.timestamp()),),
    ).fetchall()
    for row in rows:
        key = trend_date(row["created_at"])
        if key not in trend:
            continue
        bucket = "success" if row["result"] == "success" else "failed"
        trend[key][bucket] += 1

    stock = get_setting(conn, "stock_snapshot") or {"updated_at": 0, "items": [], "warnings": []}
    return {
        "ok": True,
        "overview": overview,
        "trend": list(trend.values()),
        "stock": stock,
        "recent_logs": list_access_logs(conn, limit=30),
    }


def public_stock_thresholds(conn) -> dict:
    raw = get_setting(conn, "stock_thresholds") or {}
    return {"thresholds": raw.get("thresholds", [])}


def security_summary_payload(conn) -> dict:
    ts = now_ts()
    abnormal: dict[str, dict] = {}
    for row in conn.execute("SELECT key, failures, updated_at FROM login_failures WHERE updated_at >= ? AND failures >= 5", (ts - 900,)):
        key = str(row["key"] or "")
        ip = key.split(":", 1)[0] if ":" in key else key
        abnormal[ip] = {"ip": ip, "type": "login_failed", "count": int(row["failures"] or 0), "updated_at": int(row["updated_at"] or 0)}
    for row in conn.execute(
        """
        SELECT ip, COUNT(*) AS count, MAX(created_at) AS updated_at
        FROM card_access_logs
        WHERE result != 'success' AND created_at >= ?
        GROUP BY ip
        HAVING COUNT(*) >= 8
        """,
        (ts - 1800,),
    ):
        abnormal[str(row["ip"])] = {"ip": row["ip"], "type": "redeem_failed", "count": int(row["count"] or 0), "updated_at": int(row["updated_at"] or 0)}
    return {
        "ok": True,
        "turnstile": {
            **turnstile_public_settings(conn),
            "has_secret_key": bool((turnstile_raw(conn)).get("secret_key_enc") or os.environ.get("TURNSTILE_SECRET_KEY")),
        },
        "abnormal_ips": sorted(abnormal.values(), key=lambda item: item["updated_at"], reverse=True),
        "recent_audit_logs": list_admin_audit_logs(conn, limit=20),
        "recent_login_failures": list_login_failures(conn, limit=20),
    }


def require_admin(
    conn=Depends(db),
    ks_session: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE)] = None,
):
    user = get_session_user(conn, ks_session)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


@app.post("/api/admin/login")
async def login(body: LoginBody, request: Request, response: Response, conn=Depends(db)):
    ip = client_ip(request)
    username = body.username.strip()
    normalized_username = username.lower()
    login_lock_key = f"{ip}:{normalized_username}"
    try:
        await REDEEM_GUARD.check_counter_limit("admin-login-ip", ip, limit=30, window_seconds=300)
        await REDEEM_GUARD.check_counter_limit("admin-login-user", normalized_username, limit=50, window_seconds=900)
        await REDEEM_GUARD.check_counter_limit(
            "admin-login-pair",
            f"{ip}\0{normalized_username}",
            limit=8,
            window_seconds=300,
        )
    except (RedeemGuardUnavailable, RedeemRateLimited) as exc:
        raise redeem_guard_http_error(exc) from exc
    if is_login_locked(conn, login_lock_key):
        record_audit(conn, request, "login", actor={"username": username}, result="locked")
        raise HTTPException(status_code=429, detail="登录失败次数过多，请 15 分钟后再试")
    try:
        await asyncio.to_thread(
            verify_turnstile_token,
            conn,
            body.turnstile_token,
            ip,
            expected_hostname="admin.example.com",
            expected_action="admin_login",
        )
    except HTTPException:
        record_audit(conn, request, "login", actor={"username": username}, result="turnstile_failed")
        raise
    user = await asyncio.to_thread(authenticate, conn, username, body.password)
    if not user:
        record_login_failure(conn, login_lock_key, max_attempts=LOGIN_LOCK_ATTEMPTS, lock_seconds=LOGIN_LOCK_SECONDS)
        record_audit(conn, request, "login", actor={"username": username}, result="failed")
        raise HTTPException(status_code=401, detail="账号或密码错误")
    clear_login_failures(conn, login_lock_key)
    session_token = create_session(conn, user["id"])
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=604800,
        path="/",
    )
    # CSRF 双提交 Cookie Token：非 HttpOnly，供前端读取并回传 X-CSRF-Token。
    issue_csrf_cookie(response)
    record_audit(conn, request, "login", actor=user, result="ok")
    return {"ok": True, "user": user}


@app.post("/api/admin/logout")
def logout(
    request: Request,
    response: Response,
    user=Depends(require_admin),
    conn=Depends(db),
    ks_session: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE)] = None,
):
    delete_session(conn, ks_session)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    record_audit(conn, request, "logout", actor=user, result="ok")
    return {"ok": True}


@app.get("/api/admin/me")
def me(
    response: Response,
    user=Depends(require_admin),
    csrf_token: Annotated[Optional[str], Cookie(alias=CSRF_COOKIE)] = None,
):
    if not csrf_token:
        issue_csrf_cookie(response)
    return {"ok": True, "user": user}


@app.get("/api/admin/dashboard")
def api_dashboard(user=Depends(require_admin), conn=Depends(db)):
    return dashboard_payload(conn)


@app.put("/api/admin/profile")
def update_profile(body: ProfileBody, request: Request, user=Depends(require_admin), conn=Depends(db)):
    conn.execute("UPDATE admin_users SET email = ?, avatar = ? WHERE id = ?", (body.email.strip(), body.avatar, user["id"]))
    conn.commit()
    row = conn.execute("SELECT * FROM admin_users WHERE id = ?", (user["id"],)).fetchone()
    from .db import public_user

    record_audit(conn, request, "update_profile", actor=user, target=f"user_id={user['id']}", result="ok")
    return {"ok": True, "user": public_user(row)}


@app.put("/api/admin/password")
def update_password(body: PasswordBody, request: Request, response: Response, user=Depends(require_admin), conn=Depends(db)):
    row = conn.execute("SELECT password_hash FROM admin_users WHERE id = ?", (user["id"],)).fetchone()
    if not row or not verify_password(body.current_password, row["password_hash"]):
        record_audit(conn, request, "change_password", actor=user, target=f"user_id={user['id']}", result="failed")
        raise HTTPException(status_code=400, detail="当前密码错误")
    if secrets.compare_digest(body.current_password, body.new_password):
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")
    conn.execute("UPDATE admin_users SET password_hash = ? WHERE id = ?", (hash_password(body.new_password), user["id"]))
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    conn.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    record_audit(conn, request, "change_password", actor=user, target=f"user_id={user['id']}", result="ok")
    return {"ok": True}


@app.get("/api/admin/settings/sub2api")
def get_sub2api_settings(user=Depends(require_admin), conn=Depends(db)):
    raw = get_setting(conn, "sub2api") or {}
    return {
        "ok": True,
        "settings": {
            "base_url": raw.get("base_url") or os.environ.get("SUB2API_BASE_URL") or "http://127.0.0.1:5220",
            "has_api_key": bool(raw.get("api_key_enc") or os.environ.get("SUB2API_API_KEY")),
            "has_bearer_token": bool(raw.get("bearer_token_enc") or os.environ.get("SUB2API_BEARER_TOKEN")),
        },
    }


@app.get("/api/public/login-settings")
def public_login_settings(conn=Depends(db)):
    return {"ok": True, "turnstile": turnstile_public_settings(conn)}


@app.get("/api/public/redeem-settings")
async def public_redeem_settings(request: Request, conn=Depends(db)):
    ip = client_ip(request)
    try:
        required = await REDEEM_GUARD.challenge_required(ip)
    except RedeemGuardUnavailable as exc:
        raise redeem_guard_http_error(exc) from exc
    site_key = turnstile_site_key(conn)
    if required and (not site_key or not turnstile_secret(conn)):
        raise HTTPException(
            status_code=503,
            detail="人机验证尚未配置，请联系管理员",
            headers={"Retry-After": "30"},
        )
    return {"ok": True, "turnstile": {"required": required, "site_key": site_key if required else ""}}


@app.put("/api/admin/settings/sub2api")
def put_sub2api_settings(body: Sub2APISettingsBody, request: Request, user=Depends(require_admin), conn=Depends(db)):
    put_setting(
        conn,
        "sub2api",
        {
            "base_url": clean_base_url(body.base_url),
            "api_key_enc": encrypt(body.api_key.strip()),
            "bearer_token_enc": encrypt(body.bearer_token.strip()),
        },
    )
    record_audit(conn, request, "update_settings", actor=user, target="sub2api", result="ok")
    return {"ok": True}


@app.get("/api/admin/settings/turnstile")
def get_turnstile_settings(user=Depends(require_admin), conn=Depends(db)):
    raw = turnstile_raw(conn)
    public = turnstile_public_settings(conn)
    return {
        "ok": True,
        "settings": {
            "enabled": public["enabled"],
            "site_key": public["site_key"],
            "has_secret_key": bool(raw.get("secret_key_enc") or os.environ.get("TURNSTILE_SECRET_KEY")),
        },
    }


@app.put("/api/admin/settings/turnstile")
def put_turnstile_settings(body: TurnstileSettingsBody, request: Request, user=Depends(require_admin), conn=Depends(db)):
    site_key = body.site_key.strip()
    existing = turnstile_raw(conn)
    secret_key = body.secret_key.strip()
    secret_key_enc = encrypt(secret_key) if secret_key else existing.get("secret_key_enc", "")
    if body.enabled and (not site_key or not (secret_key_enc or os.environ.get("TURNSTILE_SECRET_KEY"))):
        raise HTTPException(status_code=400, detail="启用 Turnstile 前请填写站点密钥和私密密钥")
    put_setting(conn, "turnstile", {"enabled": body.enabled, "site_key": site_key, "secret_key_enc": secret_key_enc})
    record_audit(conn, request, "update_settings", actor=user, target="turnstile", result="ok")
    return {"ok": True}


@app.get("/api/admin/settings/stock-thresholds")
def get_stock_thresholds(user=Depends(require_admin), conn=Depends(db)):
    return {"ok": True, "settings": public_stock_thresholds(conn)}


@app.put("/api/admin/settings/stock-thresholds")
def put_stock_thresholds(body: StockThresholdsBody, request: Request, user=Depends(require_admin), conn=Depends(db)):
    thresholds = [item.model_dump() for item in body.thresholds]
    put_setting(conn, "stock_thresholds", {"thresholds": thresholds})
    record_audit(conn, request, "update_settings", actor=user, target="stock_thresholds", result="ok")
    return {"ok": True}


@app.post("/api/admin/stock/check")
async def check_stock(request: Request, user=Depends(require_admin), conn=Depends(db)):
    thresholds = [item for item in public_stock_thresholds(conn).get("thresholds", []) if item.get("enabled", True)]
    client = Sub2APIClient(sub2api_settings_from_db(conn))
    extracted_account_ids = allocated_ids(conn)
    items = []
    warnings = []
    for threshold in thresholds:
        group_id = str(threshold.get("group_id") or "")
        if not group_id:
            continue
        try:
            accounts = await client.accounts(group_id)
        except ValueError as exc:
            try_notify(conn, "sub2api_stock_error", "sub2api 库存检查失败", str(exc))
            record_audit(conn, request, "stock_check", actor=user, target=f"group={group_id}", result="failed")
            raise HTTPException(status_code=400, detail=str(exc))
        group_account_ids = {
            str(account.get("_sub2api_id") or account.get("id") or account.get("account_id") or account.get("name") or "")
            for account in accounts
        }
        group_account_ids.discard("")
        allocated = group_account_ids & extracted_account_ids
        total = len(accounts)
        available = max(0, total - len(allocated))
        row = {
            "group_id": group_id,
            "group_name": threshold.get("group_name") or group_id,
            "total": total,
            "allocated": len(allocated),
            "available": available,
            "min_available": int(threshold.get("min_available") or 0),
        }
        items.append(row)
        if available < row["min_available"]:
            warnings.append(row)
    snapshot = {"updated_at": now_ts(), "items": items, "warnings": warnings}
    put_setting(conn, "stock_snapshot", snapshot)
    if warnings:
        text = "\n".join(f"{item['group_name']}：可用 {item['available']}，阈值 {item['min_available']}" for item in warnings)
        try_notify(conn, "stock_low", "卡密系统库存不足提醒", text)
    record_audit(conn, request, "stock_check", actor=user, target=f"warnings={len(warnings)}", result="ok")
    return {"ok": True, "stock": snapshot}


@app.get("/api/admin/settings/smtp")
def get_smtp_settings(user=Depends(require_admin), conn=Depends(db)):
    return {"ok": True, "settings": public_smtp_settings(conn)}


@app.put("/api/admin/settings/smtp")
def put_smtp_settings(body: SMTPSettingsBody, request: Request, user=Depends(require_admin), conn=Depends(db)):
    existing = get_setting(conn, "smtp") or {}
    password_enc = encrypt(body.password) if body.password else existing.get("password_enc", "")
    if body.enabled and (not body.host.strip() or not body.from_email.strip() or not body.to_email.strip()):
        raise HTTPException(status_code=400, detail="启用邮件通知前请填写 SMTP 主机、发件邮箱和收件邮箱")
    put_setting(
        conn,
        "smtp",
        {
            "enabled": body.enabled,
            "host": body.host.strip(),
            "port": body.port,
            "username": body.username.strip(),
            "password_enc": password_enc,
            "from_email": body.from_email.strip(),
            "to_email": body.to_email.strip(),
            "use_ssl": body.use_ssl,
            "use_tls": body.use_tls,
        },
    )
    record_audit(conn, request, "update_settings", actor=user, target="smtp", result="ok")
    return {"ok": True}


@app.post("/api/admin/settings/smtp/test")
def test_smtp_settings(request: Request, user=Depends(require_admin), conn=Depends(db)):
    settings = private_smtp_settings(conn)
    try:
        send_smtp(settings, "卡密系统测试邮件", "如果你收到这封邮件，说明 SMTP 通知配置可用。")
    except Exception as exc:
        record_audit(conn, request, "smtp_test", actor=user, target="smtp", result="failed")
        raise HTTPException(status_code=400, detail=str(exc))
    record_audit(conn, request, "smtp_test", actor=user, target="smtp", result="ok")
    return {"ok": True}


@app.get("/api/admin/sub2api/groups")
async def sub2api_groups(user=Depends(require_admin), conn=Depends(db)):
    try:
        groups = await Sub2APIClient(sub2api_settings_from_db(conn)).groups()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "groups": groups}


@app.get("/api/admin/sub2api/accounts")
async def sub2api_accounts(group_id: str, user=Depends(require_admin), conn=Depends(db)):
    try:
        accounts = await Sub2APIClient(sub2api_settings_from_db(conn)).accounts(group_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "accounts": accounts}


@app.get("/api/admin/account-pool")
async def api_account_pool(user=Depends(require_admin), conn=Depends(db)):
    client = Sub2APIClient(sub2api_settings_from_db(conn))
    try:
        groups, raw_accounts = await asyncio.gather(client.groups(), client.accounts())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    allocations = {
        str(row["sub2api_account_id"]): dict(row)
        for row in conn.execute(
            """
            SELECT a.sub2api_account_id, a.test_status, a.allocated_at,
                   c.id AS card_id, c.code AS card_code, c.status AS card_status
            FROM account_allocations a
            JOIN cards c ON c.id = a.card_id
            """
        )
    }
    manual_extractions = manual_extracted_accounts(conn)
    extracted_account_ids = set(allocations) | set(manual_extractions)
    group_names = {str(group["id"]): str(group["name"]) for group in groups}
    group_members = {group_id: set() for group_id in group_names}
    accounts = []

    for raw in raw_accounts:
        account_id = str(raw.get("_sub2api_id") or raw.get("id") or raw.get("account_id") or raw.get("name") or "")
        if not account_id:
            continue
        account_groups = []
        seen_group_ids = set()
        for raw_group in raw.get("groups") or []:
            if not isinstance(raw_group, dict):
                continue
            group_id = str(raw_group.get("id") or raw_group.get("group_id") or "")
            if not group_id or group_id in seen_group_ids:
                continue
            group_name = str(raw_group.get("name") or raw_group.get("group_name") or group_names.get(group_id) or group_id)
            group_names.setdefault(group_id, group_name)
            group_members.setdefault(group_id, set()).add(account_id)
            account_groups.append({"id": group_id, "name": group_name})
            seen_group_ids.add(group_id)
        for raw_group_id in raw.get("group_ids") or []:
            group_id = str(raw_group_id)
            if not group_id or group_id in seen_group_ids:
                continue
            group_name = group_names.get(group_id, group_id)
            group_members.setdefault(group_id, set()).add(account_id)
            account_groups.append({"id": group_id, "name": group_name})
            seen_group_ids.add(group_id)

        allocation = allocations.get(account_id)
        manual_extraction = manual_extractions.get(account_id)
        accounts.append(
            {
                "id": account_id,
                "name": str(raw.get("name") or raw.get("email") or account_id),
                "type": str(raw.get("type") or ""),
                "platform": str(raw.get("platform") or ""),
                "status": str(raw.get("status") or ""),
                "schedulable": bool(raw.get("schedulable")),
                "concurrency": int(raw.get("concurrency") or 0),
                "current_concurrency": int(raw.get("current_concurrency") or 0),
                "error_message": str(raw.get("error_message") or "")[:300],
                "groups": account_groups,
                "allocated": account_id in extracted_account_ids,
                "manual_extracted": manual_extraction is not None,
                "manual_extracted_at": manual_extraction["extracted_at"] if manual_extraction else None,
                "allocation": (
                    {
                        "card_id": allocation["card_id"],
                        "card_code": allocation["card_code"],
                        "card_status": allocation["card_status"],
                        "test_status": allocation["test_status"],
                        "allocated_at": allocation["allocated_at"],
                    }
                    if allocation
                    else None
                ),
            }
        )

    accounts.sort(key=lambda account: (account["name"].lower(), account["id"]))
    group_rows = []
    for group_id, group_name in group_names.items():
        members = group_members.get(group_id, set())
        allocated = len(members & extracted_account_ids)
        group_rows.append(
            {
                "id": group_id,
                "name": group_name,
                "total": len(members),
                "allocated": allocated,
                "unallocated": len(members) - allocated,
            }
        )
    allocated_count = sum(1 for account in accounts if account["allocated"])
    return {
        "ok": True,
        "updated_at": now_ts(),
        "summary": {
            "group_count": len(group_rows),
            "account_count": len(accounts),
            "allocated_count": allocated_count,
            "unallocated_count": len(accounts) - allocated_count,
        },
        "groups": group_rows,
        "accounts": accounts,
    }


@app.put("/api/admin/account-pool/{account_id}/extraction-status")
def api_set_account_extraction_status(
    account_id: str,
    body: AccountExtractionStatusBody,
    request: Request,
    user=Depends(require_admin),
    conn=Depends(db),
):
    account_id = account_id.strip()
    if not account_id or len(account_id) > 300:
        raise HTTPException(status_code=400, detail="账号 ID 无效")
    try:
        result = set_account_extracted(conn, account_id, body.account_name, body.extracted)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    record_audit(
        conn,
        request,
        "set_account_extraction_status",
        actor=user,
        target=f"account_id={account_id},extracted={str(body.extracted).lower()}",
        result="ok",
    )
    return {"ok": True, **result}


@app.get("/api/admin/batches")
def api_batches(user=Depends(require_admin), conn=Depends(db)):
    return {"ok": True, "batches": list_batches(conn)}


@app.post("/api/admin/batches/bulk-delete")
def api_bulk_delete_batches(body: BulkDeleteBody, request: Request, user=Depends(require_admin), conn=Depends(db)):
    deleted = bulk_delete_batches(conn, body.ids)
    record_audit(conn, request, "bulk_delete_batches", actor=user, target=f"count={deleted}", result="ok")
    return {"ok": True, "deleted": deleted}


@app.delete("/api/admin/batches/{batch_id}")
def api_delete_batch(batch_id: int, request: Request, user=Depends(require_admin), conn=Depends(db)):
    if not delete_batch(conn, batch_id):
        record_audit(conn, request, "delete_batch", actor=user, target=f"batch_id={batch_id}", result="failed")
        raise HTTPException(status_code=404, detail="批次不存在")
    record_audit(conn, request, "delete_batch", actor=user, target=f"batch_id={batch_id}", result="ok")
    return {"ok": True}


@app.post("/api/admin/cards/generate")
def api_generate_cards(body: GenerateCardsBody, request: Request, user=Depends(require_admin), conn=Depends(db)):
    batch_id = body.batch_id
    try:
        if not batch_id:
            batch = create_batch(conn, body.batch_name or f"{body.group_name} 批次", body.batch_note)
            batch_id = batch["id"]
        cards = create_cards(
            conn,
            batch_id=batch_id,
            group_id=body.group_id,
            group_name=body.group_name,
            account_count=body.account_count,
            generate_count=body.generate_count,
            days=body.days,
            points=body.points,
        )
    except ValueError as exc:
        record_audit(conn, request, "generate_cards", actor=user, target=f"group={body.group_id},count={body.generate_count}", result="failed")
        raise HTTPException(status_code=400, detail=str(exc))
    record_audit(conn, request, "generate_cards", actor=user, target=f"batch_id={batch_id},group={body.group_id},count={len(cards)}", result="ok")
    return {"ok": True, "cards": cards}


@app.get("/api/admin/cards")
def api_cards(
    status: str = "",
    batch_id: Optional[int] = None,
    group_id: str = "",
    keyword: str = "",
    limit: int = 1000,
    user=Depends(require_admin),
    conn=Depends(db),
):
    return {
        "ok": True,
        "cards": list_cards(conn, limit=limit, status=status, batch_id=batch_id, group_id=group_id, keyword=keyword.strip()),
    }


@app.get("/api/admin/cards/{card_id}")
def api_card_detail(card_id: int, user=Depends(require_admin), conn=Depends(db)):
    card = get_card(conn, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="卡密不存在")
    return {
        "ok": True,
        "card": card,
        "logs": list_access_logs(conn, card_id=card_id),
        "allocations": list_account_allocations(conn, card_id),
    }


@app.get("/api/admin/logs")
def api_logs(
    card_id: Optional[int] = None,
    result: str = "",
    keyword: str = "",
    limit: int = 1000,
    user=Depends(require_admin),
    conn=Depends(db),
):
    return {"ok": True, "logs": list_access_logs(conn, limit=limit, card_id=card_id, result=result, keyword=keyword.strip())}


@app.post("/api/admin/logs/bulk-delete")
def api_bulk_delete_logs(body: BulkDeleteBody, request: Request, user=Depends(require_admin), conn=Depends(db)):
    deleted = bulk_delete_access_logs(conn, body.ids)
    record_audit(conn, request, "bulk_delete_access_logs", actor=user, target=f"count={deleted}", result="ok")
    return {"ok": True, "deleted": deleted}


@app.put("/api/admin/cards/{card_id}/status")
def api_set_card_status(card_id: int, body: StatusBody, request: Request, user=Depends(require_admin), conn=Depends(db)):
    try:
        card = set_card_status(conn, card_id, body.status)
    except ValueError as exc:
        record_audit(conn, request, "set_card_status", actor=user, target=f"card_id={card_id},status={body.status}", result="failed")
        raise HTTPException(status_code=400, detail=str(exc))
    record_audit(conn, request, "set_card_status", actor=user, target=f"card_id={card_id},status={body.status}", result="ok")
    return {"ok": True, "card": card}


@app.post("/api/admin/cards/bulk-status")
def api_bulk_card_status(body: BulkStatusBody, request: Request, user=Depends(require_admin), conn=Depends(db)):
    try:
        updated = bulk_set_card_status(conn, body.ids, body.status)
    except ValueError as exc:
        record_audit(conn, request, "bulk_set_card_status", actor=user, target=f"status={body.status},count={len(body.ids)}", result="failed")
        raise HTTPException(status_code=400, detail=str(exc))
    record_audit(conn, request, "bulk_set_card_status", actor=user, target=f"status={body.status},count={updated}", result="ok")
    return {"ok": True, "updated": updated}


@app.delete("/api/admin/cards/{card_id}")
def api_delete_card(card_id: int, request: Request, user=Depends(require_admin), conn=Depends(db)):
    conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
    conn.commit()
    record_audit(conn, request, "delete_card", actor=user, target=f"card_id={card_id}", result="ok")
    return {"ok": True}


@app.post("/api/admin/cards/bulk-delete")
def api_bulk_delete_cards(body: BulkDeleteBody, request: Request, user=Depends(require_admin), conn=Depends(db)):
    ids = sorted({int(item) for item in body.ids if int(item) > 0})
    if ids:
        placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM cards WHERE id IN ({placeholders})", ids)
        conn.commit()
    record_audit(conn, request, "bulk_delete_cards", actor=user, target=f"count={len(ids)}", result="ok")
    return {"ok": True, "deleted": len(ids)}


@app.get("/api/admin/security/summary")
def api_security_summary(user=Depends(require_admin), conn=Depends(db)):
    return security_summary_payload(conn)


@app.get("/api/admin/security/audit-logs")
def api_security_audit_logs(limit: int = 200, user=Depends(require_admin), conn=Depends(db)):
    return {"ok": True, "logs": list_admin_audit_logs(conn, limit=max(1, min(limit, 1000)))}


@app.get("/api/admin/security/login-failures")
def api_security_login_failures(limit: int = 200, user=Depends(require_admin), conn=Depends(db)):
    return {"ok": True, "failures": list_login_failures(conn, limit=max(1, min(limit, 1000)))}


async def prepare_redeem_download(card: dict, conn) -> tuple[list[dict], bytes]:
    client = Sub2APIClient(sub2api_settings_from_db(conn))
    accounts = await client.accounts(card["group_id"])
    used = allocated_ids(conn)
    live: list[dict] = []
    for account in accounts:
        account_id = str(account.get("_sub2api_id") or account.get("id") or account.get("name") or "")
        if not account_id or account_id in used:
            continue
        ok, _message = await client.test_account(account_id)
        if ok:
            live.append(account)
        if len(live) >= int(card["account_count"]):
            break
    if len(live) < int(card["account_count"]):
        raise InsufficientAccountsError(f"可用账号不足，需要 {card['account_count']} 个，当前 {len(live)} 个")
    download_accounts = exported_accounts_for(live, await client.export_accounts())
    content = build_accounts_zip(str(card["code"]), download_accounts)
    return live, content


@app.post("/api/redeem")
async def redeem(body: RedeemBody, request: Request, conn=Depends(db)):
    code = body.code.strip().upper()
    ip = client_ip(request)
    ua = (request.headers.get("user-agent", "") or "")[:500]
    deadline = asyncio.get_running_loop().time() + REDEEM_PREPARE_TIMEOUT_SECONDS
    try:
        await REDEEM_GUARD.check_rate_limits(ip, code)
        challenge_required = await REDEEM_GUARD.challenge_required(ip)
    except (RedeemGuardUnavailable, RedeemRateLimited) as exc:
        raise redeem_guard_http_error(exc) from exc
    if challenge_required:
        try:
            async with REDEEM_GUARD.admission(code):
                await asyncio.wait_for(
                    asyncio.to_thread(
                        verify_turnstile_token,
                        conn,
                        body.turnstile_token,
                        ip,
                        required=True,
                        expected_hostname="buyer.example.com",
                        expected_action="buyer_redeem",
                    ),
                    timeout=max(0, deadline - asyncio.get_running_loop().time()),
                )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="提取处理超时，请稍后重试")
        except (RedeemGuardUnavailable, RedeemCardBusy, RedeemServerBusy) as exc:
            raise redeem_guard_http_error(exc) from exc

    if not code or not CARD_CODE_RE.fullmatch(code):
        log_access(conn, None, ip, ua, "invalid", safe_log_value(code))
        await record_buyer_redeem_failure(ip)
        maybe_notify_redeem_abnormal(conn, ip)
        raise HTTPException(status_code=400, detail=GENERIC_CARD_ERROR)
    row = conn.execute("SELECT * FROM cards WHERE code = ?", (code,)).fetchone()
    if not row:
        log_access(conn, None, ip, ua, "not_found", safe_log_value(code))
        await record_buyer_redeem_failure(ip)
        maybe_notify_redeem_abnormal(conn, ip)
        raise HTTPException(status_code=400, detail=GENERIC_CARD_ERROR)
    card = rowdict(row) or {}
    if card["status"] != "unused":
        log_access(conn, card["id"], ip, ua, "blocked", f"status={card['status']}")
        await record_buyer_redeem_failure(ip)
        maybe_notify_redeem_abnormal(conn, ip)
        detail = "卡密已被使用" if card["status"] == "used" else GENERIC_CARD_ERROR
        raise HTTPException(status_code=400, detail=detail)
    if card["expires_at"] and now_ts() > card["expires_at"]:
        log_access(conn, card["id"], ip, ua, "expired", "")
        await record_buyer_redeem_failure(ip)
        maybe_notify_redeem_abnormal(conn, ip)
        raise HTTPException(status_code=400, detail=GENERIC_CARD_ERROR)

    try:
        async with REDEEM_GUARD.admission(code):
            try:
                live, content = await asyncio.wait_for(
                    prepare_redeem_download(card, conn),
                    timeout=max(0, deadline - asyncio.get_running_loop().time()),
                )
            except asyncio.TimeoutError:
                log_access(conn, card["id"], ip, ua, "timeout", "sub2api preparation timed out")
                try_notify(conn, "sub2api_redeem_timeout", "sub2api 提取超时提醒", f"card_id={card['id']}")
                raise HTTPException(status_code=504, detail="提取处理超时，请稍后重试")
            except InsufficientAccountsError as exc:
                log_access(conn, card["id"], ip, ua, "insufficient", str(exc))
                maybe_notify_redeem_abnormal(conn, ip)
                raise HTTPException(status_code=409, detail="暂时没有足够可用账号，请联系管理员")
            except ValueError as exc:
                log_access(conn, card["id"], ip, ua, "sub2api_error", str(exc))
                try_notify(conn, "sub2api_redeem_error", "sub2api 提取失败提醒", str(exc))
                maybe_notify_redeem_abnormal(conn, ip)
                raise HTTPException(status_code=400, detail="暂时无法提取，请联系管理员")

            try:
                mark_card_used(conn, card["id"], body.user.strip() or ip, live)
            except ValueError as exc:
                log_access(conn, card["id"], ip, ua, "blocked", str(exc))
                await record_buyer_redeem_failure(ip)
                maybe_notify_redeem_abnormal(conn, ip)
                raise HTTPException(status_code=400, detail=GENERIC_CARD_ERROR)
    except (RedeemGuardUnavailable, RedeemRateLimited, RedeemCardBusy, RedeemServerBusy) as exc:
        raise redeem_guard_http_error(exc) from exc

    try:
        log_access(conn, card["id"], ip, ua, "success", f"{len(live)} 个账号")
    except Exception:
        logger.exception("兑换成功日志写入失败: card_id=%s", card["id"])
    try:
        await REDEEM_GUARD.clear_failures(ip)
    except RedeemGuardUnavailable:
        logger.warning("兑换成功后清理 Redis 失败计数失败，等待 TTL 自动过期")
    filename = safe_zip_name(code)
    return Response(
        content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if ADMIN_STATIC_DIR.is_dir():
    app.mount("/admin-static", StaticFiles(directory=ADMIN_STATIC_DIR), name="admin-static")
if BUYER_STATIC_DIR.is_dir():
    app.mount("/buyer-static", StaticFiles(directory=BUYER_STATIC_DIR), name="buyer-static")


def frontend_root_for_host(host: str) -> tuple[Path, str]:
    if host in BUYER_HOSTS and (BUYER_STATIC_DIR / "buyer.html").is_file():
        return BUYER_STATIC_DIR, "buyer.html"
    if (ADMIN_STATIC_DIR / "admin.html").is_file():
        return ADMIN_STATIC_DIR, "admin.html"
    return STATIC_DIR, "index.html"


@app.get("/{path:path}")
@app.head("/{path:path}")
def spa(path: str, request: Request):
    frontend_root, index_name = frontend_root_for_host(request_host(request))
    index = frontend_root / index_name
    if not index.exists():
        raise HTTPException(status_code=404, detail="frontend not built")
    if is_sensitive_spa_path(path):
        raise HTTPException(status_code=404, detail="Not Found")
    requested = (frontend_root / path).resolve()
    if path:
        try:
            requested.relative_to(frontend_root.resolve())
            if requested.exists() and requested.is_file():
                return FileResponse(requested)
        except ValueError:
            pass
    return FileResponse(index)
