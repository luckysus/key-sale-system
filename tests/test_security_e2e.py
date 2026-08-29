import asyncio
import os
import tempfile
import time
import unittest
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile

# 在导入 backend.main 之前配置隔离环境：独立 DB、固定管理员口令、关闭 Secure 便于 TestClient 回传 cookie。
_TMP_DIR = tempfile.mkdtemp(prefix="ks_sec_test_")
os.environ["DB_PATH"] = str(Path(_TMP_DIR) / "sale.sqlite")
os.environ["APP_SECRET"] = "unit-test-secret-key-please-do-not-use-in-prod-0123456789"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "unit-test-pass-123456"
os.environ["COOKIE_SECURE"] = "0"
os.environ["ALLOWED_HOSTS"] = "admin.example.com,buyer.example.com,localhost,127.0.0.1,testserver"
os.environ.pop("ENABLE_API_DOCS", None)
os.environ.pop("TRUSTED_PROXIES", None)
os.environ.pop("TURNSTILE_ENABLED", None)
os.environ.pop("TURNSTILE_SITE_KEY", None)
os.environ.pop("TURNSTILE_SECRET_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from backend import main as backend_main  # noqa: E402
from backend.redeem_guard import (  # noqa: E402
    RedeemCardBusy,
    RedeemGuardUnavailable,
    RedeemRateLimited,
    RedeemServerBusy,
)
from backend.security import resolve_client_ip  # noqa: E402


ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "unit-test-pass-123456"


class StubAdmission:
    def __init__(self, error=None, guard=None):
        self.error = error
        self.guard = guard

    async def __aenter__(self):
        if self.error:
            raise self.error
        if self.guard:
            self.guard.in_admission = True

    async def __aexit__(self, exc_type, exc, traceback):
        if self.guard:
            self.guard.in_admission = False
        return False


class StubRedeemGuard:
    def __init__(self):
        self.challenge = False
        self.rate_error = None
        self.admission_error = None
        self.failure_count = 0
        self.clear_count = 0
        self.in_admission = False
        self.counter_checks = []
        self.counter_error = None

    async def ensure_available(self):
        if isinstance(self.rate_error, RedeemGuardUnavailable):
            raise self.rate_error

    async def check_rate_limits(self, ip, code):
        if self.rate_error:
            raise self.rate_error

    async def check_counter_limit(self, scope, identity, *, limit, window_seconds):
        self.counter_checks.append((scope, identity, limit, window_seconds))
        if self.counter_error:
            raise self.counter_error

    async def challenge_required(self, ip):
        return self.challenge

    async def record_failure(self, ip):
        self.failure_count += 1
        return self.failure_count

    async def clear_failures(self, ip):
        self.clear_count += 1

    def admission(self, code):
        return StubAdmission(self.admission_error, self)


backend_main.REDEEM_GUARD = StubRedeemGuard()


class DocsDisabledTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(backend_main.app)

    def test_docs_endpoints_return_404_by_default(self):
        for path in ("/docs", "/redoc", "/openapi.json"):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_sensitive_spa_path_blocks_encoded_dotfiles(self):
        self.assertTrue(backend_main.is_sensitive_spa_path("%2eenv"))
        self.assertTrue(backend_main.is_sensitive_spa_path("data%2fsale.sqlite"))
        self.assertTrue(backend_main.is_sensitive_spa_path("wp-admin/"))
        self.assertTrue(backend_main.is_sensitive_spa_path("wp-login.php"))


class SecurityHeadersTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(backend_main.app)

    def test_security_headers_present_on_api_response(self):
        resp = self.client.get("/api/admin/me")  # 未登录 401，但仍应带安全头
        headers = resp.headers
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("Referrer-Policy", headers)
        self.assertIn("Permissions-Policy", headers)
        self.assertIn("Content-Security-Policy", headers)
        self.assertEqual(headers.get("X-Robots-Tag"), "noindex, nofollow")
        # CSP 需兼容 Ant Design Vue 的内联样式
        self.assertIn("'unsafe-inline'", headers.get("Content-Security-Policy", ""))
        self.assertIn("https://challenges.cloudflare.com", headers.get("Content-Security-Policy", ""))
        self.assertIn("frame-src https://challenges.cloudflare.com", headers.get("Content-Security-Policy", ""))
        self.assertIn("img-src 'self' data:;", headers.get("Content-Security-Policy", ""))
        self.assertIn("base-uri 'none'", headers.get("Content-Security-Policy", ""))
        self.assertEqual(headers.get("Cross-Origin-Opener-Policy"), "same-origin")
        self.assertEqual(headers.get("Cross-Origin-Resource-Policy"), "same-origin")
        self.assertNotIn("Cross-Origin-Embedder-Policy", headers)

    def test_hsts_absent_on_http_but_present_on_https(self):
        http_resp = self.client.get("/api/admin/me")
        self.assertNotIn("Strict-Transport-Security", http_resp.headers)
        https_resp = self.client.get("/api/admin/me", headers={"x-forwarded-proto": "https"})
        hsts = https_resp.headers.get("Strict-Transport-Security", "")
        self.assertIn("max-age=31536000", hsts)
        self.assertIn("includeSubDomains", hsts)

    def test_redeem_rejects_oversized_body_before_parsing(self):
        resp = self.client.post("/api/redeem", content="x" * 3000, headers={"content-type": "application/json"})
        self.assertEqual(resp.status_code, 413, resp.text)
        self.assertEqual(resp.headers.get("Cache-Control"), "no-store")
        self.assertEqual(resp.headers.get("X-Robots-Tag"), "noindex, nofollow")


class CsrfDoubleSubmitTest(unittest.TestCase):
    def setUp(self):
        backend_main.REDEEM_GUARD = StubRedeemGuard()
        self.client = TestClient(backend_main.app)

    def _login(self):
        resp = self.client.post("/api/admin/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp

    def test_login_sets_non_httponly_csrf_cookie(self):
        resp = self._login()
        set_cookie = " ".join(resp.headers.get_list("set-cookie"))
        self.assertIn("csrf_token=", set_cookie)
        # csrf cookie 必须为非 HttpOnly（供前端读取），且 SameSite=Strict
        self.assertIn("samesite=strict", set_cookie.lower())
        # 确认 csrf_token 段没有 HttpOnly 标记
        csrf_segment = [c for c in resp.headers.get_list("set-cookie") if c.startswith("csrf_token=")][0]
        self.assertNotIn("httponly", csrf_segment.lower())

    def test_write_without_csrf_header_is_rejected(self):
        self._login()
        # 携带 session cookie 但不带 X-CSRF-Token 头
        resp = self.client.post("/api/admin/logout")
        self.assertEqual(resp.status_code, 403, resp.text)
        self.assertIn("CSRF", resp.text)

    def test_write_with_matching_csrf_header_passes(self):
        self._login()
        csrf = self.client.cookies.get("csrf_token")
        self.assertTrue(csrf)
        resp = self.client.post("/api/admin/logout", headers={"X-CSRF-Token": csrf})
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_me_backfills_missing_csrf_cookie_for_existing_session(self):
        from backend.db import connect, create_session

        conn = connect(backend_main.DB_PATH)
        try:
            session = create_session(conn, 1)
        finally:
            conn.close()
        self.client.cookies.set("ks_session", session)
        resp = self.client.get("/api/admin/me")
        self.assertEqual(resp.status_code, 200, resp.text)
        csrf = self.client.cookies.get("csrf_token")
        self.assertTrue(csrf)
        resp = self.client.post("/api/admin/logout", headers={"X-CSRF-Token": csrf})
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_write_with_wrong_csrf_header_is_rejected(self):
        self._login()
        resp = self.client.post("/api/admin/logout", headers={"X-CSRF-Token": "totally-wrong-token"})
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_redeem_is_exempt_from_csrf(self):
        # 买家兑换无需 CSRF：非法卡密返回 400（业务校验），而不是 403（CSRF 拦截）
        resp = self.client.post("/api/redeem", json={"code": "AAAA-BBBB-CCCC-DDDD"})
        self.assertNotEqual(resp.status_code, 403, resp.text)


class RedeemProtectionTest(unittest.TestCase):
    def setUp(self):
        from backend.db import connect

        self.guard = StubRedeemGuard()
        backend_main.REDEEM_GUARD = self.guard
        backend_main.REDEEM_PREPARE_TIMEOUT_SECONDS = 180
        self.client = TestClient(backend_main.app)
        conn = connect(backend_main.DB_PATH)
        try:
            for table in ("account_allocations", "account_allocation_history", "card_access_logs", "cards", "batches", "app_settings"):
                conn.execute(f"DELETE FROM {table}")
            conn.commit()
        finally:
            conn.close()

    def test_public_redeem_settings_reports_progressive_challenge(self):
        from backend.db import connect, put_setting

        conn = connect(backend_main.DB_PATH)
        try:
            put_setting(
                conn,
                "turnstile",
                {
                    "enabled": True,
                    "site_key": "site-key-123",
                    "secret_key_enc": backend_main.encrypt("secret-key-456"),
                },
            )
        finally:
            conn.close()
        self.guard.challenge = True

        response = self.client.get("/api/public/redeem-settings")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["turnstile"], {"required": True, "site_key": "site-key-123"})

    def test_redis_unavailable_closes_redeem_but_not_other_public_api(self):
        self.guard.rate_error = RedeemGuardUnavailable("offline")

        redeem = self.client.post("/api/redeem", json={"code": "AAAA-BBBB-CCCC-DDDD"})

        self.assertEqual(redeem.status_code, 503, redeem.text)
        self.assertEqual(redeem.headers.get("Retry-After"), "30")
        self.assertEqual(self.client.get("/api/public/login-settings").status_code, 200)

    def test_invalid_card_records_buyer_failure(self):
        response = self.client.post("/api/redeem", json={"code": "invalid-card"})

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.guard.failure_count, 1)

    def test_required_challenge_rejects_missing_token(self):
        from backend.db import connect, put_setting

        conn = connect(backend_main.DB_PATH)
        try:
            put_setting(
                conn,
                "turnstile",
                {
                    "enabled": True,
                    "site_key": "site-key-123",
                    "secret_key_enc": backend_main.encrypt("secret-key-456"),
                },
            )
        finally:
            conn.close()
        self.guard.challenge = True

        response = self.client.post("/api/redeem", json={"code": "AAAA-BBBB-CCCC-DDDD"})

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("人机验证", response.text)

    def test_busy_guard_errors_have_stable_statuses(self):
        from backend.db import connect, create_batch, create_cards

        conn = connect(backend_main.DB_PATH)
        try:
            batch = create_batch(conn, "guard status")
            card = create_cards(
                conn,
                batch_id=batch["id"],
                group_id="g1",
                group_name="team",
                account_count=1,
                generate_count=1,
                days=0,
                points=0,
            )[0]
        finally:
            conn.close()
        cases = (
            (RedeemRateLimited(60), 429),
            (RedeemCardBusy("busy"), 409),
            (RedeemServerBusy("busy"), 503),
        )
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                self.guard = StubRedeemGuard()
                backend_main.REDEEM_GUARD = self.guard
                if isinstance(error, RedeemRateLimited):
                    self.guard.rate_error = error
                else:
                    self.guard.admission_error = error
                response = self.client.post("/api/redeem", json={"code": card["code"]})
                self.assertEqual(response.status_code, expected, response.text)

    def test_preparation_timeout_does_not_consume_card(self):
        from backend.db import connect, create_batch, create_cards

        conn = connect(backend_main.DB_PATH)
        try:
            batch = create_batch(conn, "timeout")
            card = create_cards(
                conn,
                batch_id=batch["id"],
                group_id="g1",
                group_name="team",
                account_count=1,
                generate_count=1,
                days=0,
                points=0,
            )[0]
        finally:
            conn.close()

        async def slow_prepare(card_row, connection):
            await asyncio.sleep(0.02)
            return ([{"id": "a1", "name": "a1@example.com"}], b"zip")

        backend_main.REDEEM_PREPARE_TIMEOUT_SECONDS = 0.001
        with patch("backend.main.prepare_redeem_download", side_effect=slow_prepare):
            response = self.client.post("/api/redeem", json={"code": card["code"]})

        self.assertEqual(response.status_code, 504, response.text)
        conn = connect(backend_main.DB_PATH)
        try:
            status = conn.execute("SELECT status FROM cards WHERE id = ?", (card["id"],)).fetchone()["status"]
        finally:
            conn.close()
        self.assertEqual(status, "unused")

    def test_challenge_verification_runs_async_inside_admission(self):
        from backend.db import connect, put_setting

        conn = connect(backend_main.DB_PATH)
        try:
            put_setting(
                conn,
                "turnstile",
                {
                    "enabled": True,
                    "site_key": "site-key-123",
                    "secret_key_enc": backend_main.encrypt("secret-key-456"),
                },
            )
        finally:
            conn.close()
        self.guard.challenge = True
        observed = []

        async def run_in_thread(function, *args, **kwargs):
            observed.append(self.guard.in_admission)
            return function(*args, **kwargs)

        with patch("backend.main.verify_turnstile_token", return_value=None), patch(
            "backend.main.asyncio.to_thread",
            new=AsyncMock(side_effect=run_in_thread),
        ) as to_thread:
            response = self.client.post(
                "/api/redeem",
                json={"code": "invalid-card", "turnstile_token": "token-ok"},
            )

        self.assertEqual(response.status_code, 400, response.text)
        to_thread.assert_awaited_once()
        self.assertEqual(observed, [True])

    def test_challenge_time_counts_toward_total_redeem_timeout(self):
        from backend.db import connect, create_batch, create_cards, put_setting

        conn = connect(backend_main.DB_PATH)
        try:
            batch = create_batch(conn, "total timeout")
            card = create_cards(
                conn,
                batch_id=batch["id"],
                group_id="g1",
                group_name="team",
                account_count=1,
                generate_count=1,
                days=0,
                points=0,
            )[0]
            put_setting(
                conn,
                "turnstile",
                {
                    "enabled": True,
                    "site_key": "site-key-123",
                    "secret_key_enc": backend_main.encrypt("secret-key-456"),
                },
            )
        finally:
            conn.close()
        self.guard.challenge = True
        backend_main.REDEEM_PREPARE_TIMEOUT_SECONDS = 0.001

        async def slow_thread(*_args, **_kwargs):
            await asyncio.sleep(0.02)

        with patch("backend.main.asyncio.to_thread", new=AsyncMock(side_effect=slow_thread)), patch(
            "backend.main.prepare_redeem_download",
            new=AsyncMock(return_value=([{"id": "a1", "name": "a1@example.com"}], b"zip")),
        ):
            response = self.client.post(
                "/api/redeem",
                json={"code": card["code"], "turnstile_token": "token-ok"},
            )

        self.assertEqual(response.status_code, 504, response.text)
        conn = connect(backend_main.DB_PATH)
        try:
            status = conn.execute("SELECT status FROM cards WHERE id = ?", (card["id"],)).fetchone()["status"]
        finally:
            conn.close()
        self.assertEqual(status, "unused")

    def test_success_log_failure_does_not_hide_download(self):
        from backend.db import connect, create_batch, create_cards

        conn = connect(backend_main.DB_PATH)
        try:
            batch = create_batch(conn, "post-commit log")
            card = create_cards(
                conn,
                batch_id=batch["id"],
                group_id="g1",
                group_name="team",
                account_count=1,
                generate_count=1,
                days=0,
                points=0,
            )[0]
        finally:
            conn.close()

        with patch("backend.main.Sub2APIClient") as client_cls, patch(
            "backend.main.log_access",
            side_effect=OSError("disk full"),
        ), patch("backend.main.logger.exception"):
            client = client_cls.return_value
            client.accounts = AsyncMock(return_value=[{"id": "a1", "name": "a1@example.com"}])
            client.test_account = AsyncMock(return_value=(True, "ok"))
            client.export_accounts = AsyncMock(return_value=[{"id": "a1", "name": "a1@example.com"}])
            client_without_raise = TestClient(backend_main.app, raise_server_exceptions=False)
            response = client_without_raise.post("/api/redeem", json={"code": card["code"]})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers.get("content-type"), "application/zip")
        conn = connect(backend_main.DB_PATH)
        try:
            status = conn.execute("SELECT status FROM cards WHERE id = ?", (card["id"],)).fetchone()["status"]
        finally:
            conn.close()
        self.assertEqual(status, "used")


class PasswordChangeTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(backend_main.app)
        backend_main.RATE_LIMITER._hits.clear()
        self._reset_admin_password(ADMIN_PASSWORD)
        self._save_turnstile(False, "", "")

    def tearDown(self):
        self._reset_admin_password(ADMIN_PASSWORD)
        self._save_turnstile(False, "", "")

    def _reset_admin_password(self, password: str):
        from backend.db import connect
        from backend.security import hash_password

        conn = connect(backend_main.DB_PATH)
        try:
            conn.execute(
                "UPDATE admin_users SET password_hash = ? WHERE username = ?",
                (hash_password(password), ADMIN_USERNAME),
            )
            conn.execute("DELETE FROM sessions")
            conn.commit()
        finally:
            conn.close()

    def _save_turnstile(self, enabled: bool, site_key: str, secret_key: str):
        from backend.db import connect, put_setting

        conn = connect(backend_main.DB_PATH)
        try:
            put_setting(
                conn,
                "turnstile",
                {"enabled": enabled, "site_key": site_key, "secret_key_enc": backend_main.encrypt(secret_key)},
            )
        finally:
            conn.close()

    def _login(self):
        resp = self.client.post("/api/admin/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        self.assertEqual(resp.status_code, 200, resp.text)
        csrf = self.client.cookies.get("csrf_token")
        self.assertTrue(csrf)
        return csrf

    def test_change_password_rejects_wrong_current_password(self):
        csrf = self._login()
        resp = self.client.put(
            "/api/admin/password",
            headers={"X-CSRF-Token": csrf},
            json={"current_password": "wrong-password", "new_password": "new-pass-123456"},
        )
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("当前密码错误", resp.text)

        old_login = self.client.post("/api/admin/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        self.assertEqual(old_login.status_code, 200, old_login.text)

    def test_change_password_updates_password_and_invalidates_session(self):
        csrf = self._login()
        resp = self.client.put(
            "/api/admin/password",
            headers={"X-CSRF-Token": csrf},
            json={"current_password": ADMIN_PASSWORD, "new_password": "new-pass-123456"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)

        me_resp = self.client.get("/api/admin/me")
        self.assertEqual(me_resp.status_code, 401, me_resp.text)
        old_login = self.client.post("/api/admin/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        self.assertEqual(old_login.status_code, 401, old_login.text)
        new_login = self.client.post("/api/admin/login", json={"username": ADMIN_USERNAME, "password": "new-pass-123456"})
        self.assertEqual(new_login.status_code, 200, new_login.text)


class TurnstileLoginTest(unittest.TestCase):
    def setUp(self):
        backend_main.REDEEM_GUARD = StubRedeemGuard()
        self.client = TestClient(backend_main.app)
        backend_main.RATE_LIMITER._hits.clear()
        self._save_turnstile(False, "", "")

    def _save_turnstile(self, enabled: bool, site_key: str, secret_key: str):
        from backend.db import connect, put_setting

        conn = connect(backend_main.DB_PATH)
        try:
            put_setting(
                conn,
                "turnstile",
                {
                    "enabled": enabled,
                    "site_key": site_key,
                    "secret_key_enc": backend_main.encrypt(secret_key),
                },
            )
        finally:
            conn.close()

    def _login(self):
        resp = self.client.post("/api/admin/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        self.assertEqual(resp.status_code, 200, resp.text)
        return self.client.cookies.get("csrf_token")

    def test_public_login_settings_are_disabled_by_default(self):
        resp = self.client.get("/api/public/login-settings")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["turnstile"], {"enabled": False, "site_key": ""})

    def test_admin_can_save_turnstile_without_exposing_secret(self):
        csrf = self._login()
        resp = self.client.put(
            "/api/admin/settings/turnstile",
            headers={"X-CSRF-Token": csrf},
            json={"enabled": True, "site_key": "site-key-123", "secret_key": "secret-key-456"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)

        admin_resp = self.client.get("/api/admin/settings/turnstile")
        self.assertEqual(admin_resp.status_code, 200, admin_resp.text)
        self.assertEqual(
            admin_resp.json()["settings"],
            {"enabled": True, "site_key": "site-key-123", "has_secret_key": True},
        )
        self.assertNotIn("secret-key-456", admin_resp.text)

        public_resp = self.client.get("/api/public/login-settings")
        self.assertEqual(public_resp.status_code, 200, public_resp.text)
        self.assertEqual(public_resp.json()["turnstile"], {"enabled": True, "site_key": "site-key-123"})
        self.assertNotIn("secret-key-456", public_resp.text)

    def test_login_requires_turnstile_token_when_enabled(self):
        self._save_turnstile(True, "site-key-123", "secret-key-456")
        resp = self.client.post("/api/admin/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("人机验证", resp.text)

    def test_login_accepts_valid_turnstile_token(self):
        self._save_turnstile(True, "site-key-123", "secret-key-456")

        class SiteverifyResponse:
            status_code = 200

            def json(self):
                return {"success": True, "hostname": "admin.example.com", "action": "admin_login"}

        with patch("backend.main.httpx.post", return_value=SiteverifyResponse()) as siteverify:
            resp = self.client.post(
                "/api/admin/login",
                headers={"host": "admin.example.com"},
                json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD, "turnstile_token": "token-ok"},
            )

        self.assertEqual(resp.status_code, 200, resp.text)
        siteverify.assert_called_once()
        self.assertIn("siteverify", siteverify.call_args.args[0])

    def test_login_rejects_turnstile_token_for_buyer_workflow(self):
        self._save_turnstile(True, "site-key-123", "secret-key-456")

        class SiteverifyResponse:
            status_code = 200

            def json(self):
                return {"success": True, "hostname": "buyer.example.com", "action": "buyer_redeem"}

        with patch("backend.main.httpx.post", return_value=SiteverifyResponse()):
            resp = self.client.post(
                "/api/admin/login",
                headers={"host": "admin.example.com"},
                json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD, "turnstile_token": "buyer-token"},
            )

        self.assertEqual(resp.status_code, 400, resp.text)

    def test_login_rejects_correct_action_with_forged_forwarded_hostname(self):
        self._save_turnstile(True, "site-key-123", "secret-key-456")

        class SiteverifyResponse:
            status_code = 200

            def json(self):
                return {"success": True, "hostname": "evil.example", "action": "admin_login"}

        with patch("backend.main.httpx.post", return_value=SiteverifyResponse()):
            resp = self.client.post(
                "/api/admin/login",
                headers={"host": "admin.example.com", "x-forwarded-host": "evil.example"},
                json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD, "turnstile_token": "forged-host-token"},
            )

        self.assertEqual(resp.status_code, 400, resp.text)

    def test_redeem_rejects_turnstile_token_for_admin_workflow(self):
        self._save_turnstile(True, "site-key-123", "secret-key-456")
        guard = StubRedeemGuard()
        guard.challenge = True
        backend_main.REDEEM_GUARD = guard

        class SiteverifyResponse:
            status_code = 200

            def json(self):
                return {"success": True, "hostname": "admin.example.com", "action": "admin_login"}

        with patch("backend.main.httpx.post", return_value=SiteverifyResponse()):
            resp = self.client.post(
                "/api/redeem",
                headers={"host": "buyer.example.com"},
                json={"code": "AAAA-BBBB-CCCC-DDDD", "turnstile_token": "admin-token"},
            )

        self.assertEqual(resp.status_code, 403, resp.text)

    def test_redeem_rejects_correct_action_with_forged_forwarded_hostname(self):
        self._save_turnstile(True, "site-key-123", "secret-key-456")
        guard = StubRedeemGuard()
        guard.challenge = True
        backend_main.REDEEM_GUARD = guard

        class SiteverifyResponse:
            status_code = 200

            def json(self):
                return {"success": True, "hostname": "evil.example", "action": "buyer_redeem"}

        with patch("backend.main.httpx.post", return_value=SiteverifyResponse()):
            resp = self.client.post(
                "/api/redeem",
                headers={"host": "buyer.example.com", "x-forwarded-host": "evil.example"},
                json={"code": "AAAA-BBBB-CCCC-DDDD", "turnstile_token": "forged-host-token"},
            )

        self.assertEqual(resp.status_code, 403, resp.text)

    def test_redeem_accepts_turnstile_token_for_buyer_workflow(self):
        self._save_turnstile(True, "site-key-123", "secret-key-456")
        guard = StubRedeemGuard()
        guard.challenge = True
        backend_main.REDEEM_GUARD = guard

        class SiteverifyResponse:
            status_code = 200

            def json(self):
                return {"success": True, "hostname": "buyer.example.com", "action": "buyer_redeem"}

        with patch("backend.main.httpx.post", return_value=SiteverifyResponse()):
            resp = self.client.post(
                "/api/redeem",
                headers={"host": "buyer.example.com"},
                json={"code": "AAAA-BBBB-CCCC-DDDD", "turnstile_token": "buyer-token"},
            )

        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(guard.failure_count, 1, "valid buyer token must continue to card validation")

    def test_login_rejects_invalid_turnstile_token(self):
        self._save_turnstile(True, "site-key-123", "secret-key-456")

        class SiteverifyResponse:
            status_code = 200

            def json(self):
                return {"success": False}

        with patch("backend.main.httpx.post", return_value=SiteverifyResponse()):
            resp = self.client.post(
                "/api/admin/login",
                json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD, "turnstile_token": "token-bad"},
            )

        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("人机验证失败", resp.text)

    def test_redeem_does_not_use_turnstile(self):
        self._save_turnstile(True, "site-key-123", "secret-key-456")
        with patch("backend.main.httpx.post") as siteverify:
            resp = self.client.post("/api/redeem", json={"code": "AAAA-BBBB-CCCC-DDDD"})
        self.assertNotEqual(resp.status_code, 403, resp.text)
        self.assertNotIn("人机验证", resp.text)
        siteverify.assert_not_called()


class TrustedProxyClientIpTest(unittest.TestCase):
    def test_ignores_forwarded_for_when_no_trusted_proxy(self):
        # 默认不信任任何代理：忽略 X-Forwarded-For，使用直连 IP
        self.assertEqual(resolve_client_ip("203.0.113.9", "1.2.3.4", set()), "203.0.113.9")

    def test_ignores_forwarded_for_when_direct_not_trusted(self):
        self.assertEqual(resolve_client_ip("203.0.113.9", "1.2.3.4", {"127.0.0.1"}), "203.0.113.9")

    def test_uses_rightmost_untrusted_from_forwarded_for_via_trusted_proxy(self):
        # 直连来自可信代理，取最右侧非可信 IP，防止伪造头绕过限流
        self.assertEqual(
            resolve_client_ip("127.0.0.1", "9.9.9.9, 203.0.113.9", {"127.0.0.1"}),
            "203.0.113.9",
        )

    def test_skips_trusted_hops_in_forwarded_for(self):
        self.assertEqual(
            resolve_client_ip("127.0.0.1", "203.0.113.9, 127.0.0.1", {"127.0.0.1"}),
            "203.0.113.9",
        )

    def test_forged_forwarded_for_cannot_bypass_when_direct_is_public(self):
        # 攻击者从公网直连并伪造 XFF，仍只使用其真实直连 IP
        self.assertEqual(
            resolve_client_ip("198.51.100.7", "127.0.0.1, 10.0.0.1", {"127.0.0.1"}),
            "198.51.100.7",
        )


class AuditLogTest(unittest.TestCase):
    def setUp(self):
        backend_main.REDEEM_GUARD = StubRedeemGuard()
        self.client = TestClient(backend_main.app)

    def test_successful_login_writes_audit_log(self):
        self.client.post("/api/admin/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        from backend.db import connect, list_admin_audit_logs

        conn = connect(backend_main.DB_PATH)
        try:
            logs = list_admin_audit_logs(conn)
        finally:
            conn.close()
        self.assertTrue(any(row["action"] == "login" and row["result"] == "ok" for row in logs))
        # 审计日志不得包含明文密码
        joined = " ".join(str(row) for row in logs)
        self.assertNotIn(ADMIN_PASSWORD, joined)

    def test_audit_failure_is_logged_without_changing_login_result(self):
        with patch("backend.main.log_admin_audit", side_effect=RuntimeError("disk full")), patch.object(
            backend_main.logger, "exception"
        ) as log_exception:
            resp = self.client.post(
                "/api/admin/login",
                json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        log_exception.assert_called_once()


class StartupCleanupTest(unittest.TestCase):
    def test_setup_runtime_cleans_security_state(self):
        cleanup = getattr(backend_main, "cleanup_security_state", None)
        self.assertTrue(callable(cleanup), "cleanup_security_state is not wired into backend.main")
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            backend_main, "DB_PATH", Path(tmp) / "runtime.sqlite"
        ), patch.dict(os.environ, {"ADMIN_PASSWORD": ADMIN_PASSWORD}), patch.object(
            backend_main, "cleanup_security_state", wraps=cleanup
        ) as cleanup_state:
            backend_main.setup_runtime()
        cleanup_state.assert_called_once()


class HostIsolationTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(backend_main.app)

    def test_unknown_host_is_rejected(self):
        resp = self.client.get("/api/admin/me", headers={"host": "evil.example"})
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_key_domain_cannot_call_admin_api(self):
        resp = self.client.post(
            "/api/admin/login",
            headers={"host": "buyer.example.com"},
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        self.assertEqual(resp.status_code, 404, resp.text)

    def test_sale_domain_cannot_call_redeem_api(self):
        resp = self.client.post(
            "/api/redeem",
            headers={"host": "admin.example.com"},
            json={"code": "AAAA-BBBB-CCCC-DDDD"},
        )
        self.assertEqual(resp.status_code, 404, resp.text)

    def test_repeated_login_failures_are_locked_persistently(self):
        for _ in range(5):
            resp = self.client.post(
                "/api/admin/login",
                json={"username": "missing-lock-user", "password": "wrong-password"},
            )
            self.assertEqual(resp.status_code, 401, resp.text)
        resp = self.client.post(
            "/api/admin/login",
            json={"username": "missing-lock-user", "password": "wrong-password"},
        )
        self.assertEqual(resp.status_code, 429, resp.text)


class AdminLoginRedisLimitTest(unittest.TestCase):
    def setUp(self):
        from backend.db import connect, put_setting

        conn = connect(backend_main.DB_PATH)
        try:
            put_setting(conn, "turnstile", {"enabled": False, "site_key": "", "secret_key_enc": ""})
        finally:
            conn.close()
        self.guard = StubRedeemGuard()
        backend_main.REDEEM_GUARD = self.guard
        self.client = TestClient(backend_main.app)

    def test_login_checks_ip_username_and_pair_dimensions(self):
        resp = self.client.post(
            "/api/admin/login",
            headers={"host": "admin.example.com"},
            json={"username": "  admin  ", "password": ADMIN_PASSWORD},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        ip = self.guard.counter_checks[0][1] if self.guard.counter_checks else ""
        self.assertEqual(
            self.guard.counter_checks,
            [
                ("admin-login-ip", ip, 30, 300),
                ("admin-login-user", "admin", 50, 900),
                ("admin-login-pair", f"{ip}\0admin", 8, 300),
            ],
        )

    def test_login_returns_429_for_distributed_limit(self):
        self.guard.counter_error = RedeemRateLimited(300)
        resp = self.client.post(
            "/api/admin/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        self.assertEqual(resp.status_code, 429, resp.text)
        self.assertEqual(resp.headers.get("Retry-After"), "300")

    def test_login_fails_closed_when_redis_is_unavailable(self):
        self.guard.counter_error = RedeemGuardUnavailable("offline")
        resp = self.client.post(
            "/api/admin/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        self.assertEqual(resp.status_code, 503, resp.text)
        self.assertEqual(resp.headers.get("Retry-After"), "30")

    def test_existing_session_remains_available_when_redis_is_unavailable(self):
        login = self.client.post(
            "/api/admin/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.guard.counter_error = RedeemGuardUnavailable("offline")
        me = self.client.get("/api/admin/me")
        self.assertEqual(me.status_code, 200, me.text)

    def test_turnstile_and_password_verification_are_offloaded_from_event_loop(self):
        observed = []

        async def run_in_thread(function, *args, **kwargs):
            observed.append(function)
            return function(*args, **kwargs)

        with patch("backend.main.verify_turnstile_token", return_value=None) as verify_turnstile, patch(
            "backend.main.authenticate", wraps=backend_main.authenticate
        ) as verify_password, patch(
            "backend.main.asyncio.to_thread",
            new=AsyncMock(side_effect=run_in_thread),
        ) as to_thread:
            resp = self.client.post(
                "/api/admin/login",
                headers={"host": "admin.example.com"},
                json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD, "turnstile_token": "token-ok"},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(observed, [verify_turnstile, verify_password])
        self.assertEqual(to_thread.await_count, 2)


class LongRunningFeatureTest(unittest.TestCase):
    def setUp(self):
        backend_main.REDEEM_GUARD = StubRedeemGuard()
        self.client = TestClient(backend_main.app)
        backend_main.RATE_LIMITER._hits.clear()
        self._reset_data()
        self.csrf = self._login()

    def _reset_data(self):
        from backend.db import connect
        from backend.security import hash_password

        conn = connect(backend_main.DB_PATH)
        try:
            conn.execute("UPDATE admin_users SET password_hash = ? WHERE username = ?", (hash_password(ADMIN_PASSWORD), ADMIN_USERNAME))
            for table in (
                "sessions",
                "manual_extracted_accounts",
                "account_allocations",
                "account_allocation_history",
                "card_access_logs",
                "cards",
                "batches",
                "admin_audit_logs",
                "login_failures",
                "app_settings",
            ):
                conn.execute(f"DELETE FROM {table}")
            conn.commit()
        finally:
            conn.close()

    def _login(self):
        resp = self.client.post("/api/admin/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        self.assertEqual(resp.status_code, 200, resp.text)
        csrf = self.client.cookies.get("csrf_token")
        self.assertTrue(csrf)
        return csrf

    def _headers(self):
        return {"X-CSRF-Token": self.csrf}

    def _seed_cards(self):
        from backend.db import connect, create_batch, create_cards

        conn = connect(backend_main.DB_PATH)
        try:
            batch = create_batch(conn, "库存批次")
            cards = create_cards(
                conn,
                batch_id=batch["id"],
                group_id="g1",
                group_name="默认组",
                account_count=2,
                generate_count=3,
                days=0,
                points=0,
            )
            conn.execute("UPDATE cards SET status = 'used', used_by = 'buyer-ip', used_at = ?, updated_at = ? WHERE id = ?", (int(time.time()), int(time.time()), cards[0]["id"]))
            conn.execute("UPDATE cards SET status = 'disabled', updated_at = ? WHERE id = ?", (int(time.time()), cards[1]["id"]))
            conn.execute(
                "INSERT INTO account_allocations (card_id, sub2api_account_id, account_name, test_status, allocated_at) VALUES (?, ?, ?, ?, ?)",
                (cards[0]["id"], "acc-used", "visible@example.com", "alive", int(time.time())),
            )
            conn.commit()
            return batch, cards
        finally:
            conn.close()

    def test_dashboard_counts_trend_and_recent_logs(self):
        batch, cards = self._seed_cards()
        now = int(time.time())
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        from backend.db import connect

        conn = connect(backend_main.DB_PATH)
        try:
            conn.execute("INSERT INTO card_access_logs (card_id, ip, user_agent, result, message, created_at) VALUES (?, ?, ?, ?, ?, ?)", (cards[0]["id"], "1.1.1.1", "ua", "success", "ok", now))
            conn.execute("INSERT INTO card_access_logs (card_id, ip, user_agent, result, message, created_at) VALUES (?, ?, ?, ?, ?, ?)", (cards[1]["id"], "1.1.1.2", "ua", "insufficient", "low", now))
            conn.commit()
        finally:
            conn.close()

        resp = self.client.get("/api/admin/dashboard")
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["overview"]["total_cards"], 3)
        self.assertEqual(data["overview"]["unused_cards"], 1)
        self.assertEqual(data["overview"]["used_cards"], 1)
        self.assertEqual(data["overview"]["disabled_cards"], 1)
        self.assertEqual(data["overview"]["today_success"], 1)
        self.assertEqual(data["overview"]["today_failed"], 1)
        today_row = next(row for row in data["trend"] if row["date"] == today)
        self.assertEqual(today_row["success"], 1)
        self.assertEqual(today_row["failed"], 1)
        self.assertEqual(data["recent_logs"][0]["card_code"], cards[1]["code"])
        self.assertEqual(batch["name"], "库存批次")

    def test_cards_filter_detail_and_bulk_status(self):
        batch, cards = self._seed_cards()

        filtered = self.client.get(f"/api/admin/cards?status=unused&batch_id={batch['id']}&group_id=g1&keyword={cards[2]['code'][-4:]}")
        self.assertEqual(filtered.status_code, 200, filtered.text)
        self.assertEqual([card["id"] for card in filtered.json()["cards"]], [cards[2]["id"]])

        detail = self.client.get(f"/api/admin/cards/{cards[0]['id']}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["card"]["status"], "used")
        self.assertEqual(detail.json()["allocations"][0]["account_name"], "visible@example.com")
        self.assertNotIn("access_token", detail.text)

        resp = self.client.post("/api/admin/cards/bulk-status", headers=self._headers(), json={"ids": [cards[2]["id"]], "status": "disabled"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["updated"], 1)
        failed = self.client.post("/api/admin/cards/bulk-status", headers=self._headers(), json={"ids": [cards[0]["id"]], "status": "unused"})
        self.assertEqual(failed.status_code, 400, failed.text)
        self.assertIn("已使用", failed.text)

    def test_redeem_reports_used_card(self):
        _, cards = self._seed_cards()

        resp = self.client.post("/api/redeem", json={"code": cards[0]["code"]})

        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["detail"], "卡密已被使用")

    def test_account_pool_merges_groups_and_marks_allocated_accounts(self):
        from backend.db import connect, create_batch, create_cards, mark_card_used

        conn = connect(backend_main.DB_PATH)
        try:
            batch = create_batch(conn, "号池测试")
            card = create_cards(
                conn,
                batch_id=batch["id"],
                group_id="g1",
                group_name="一组",
                account_count=1,
                generate_count=1,
                days=0,
                points=0,
            )[0]
            mark_card_used(conn, card["id"], "buyer-ip", [{"id": "a1", "name": "used@example.com"}])
        finally:
            conn.close()

        accounts = [
            {
                "id": "a1",
                "name": "used@example.com",
                "status": "active",
                "type": "oauth",
                "schedulable": True,
                "concurrency": 5,
                "current_concurrency": 1,
                "groups": [{"id": "g1", "name": "一组"}, {"id": "g2", "name": "二组"}],
                "credentials": {"access_token": "secret-token"},
            },
            {
                "id": "a2",
                "name": "free@example.com",
                "status": "active",
                "type": "apikey",
                "schedulable": True,
                "groups": [{"id": "g1", "name": "一组"}],
            },
            {"id": "a3", "name": "ungrouped@example.com", "status": "active", "type": "oauth", "schedulable": True, "groups": []},
        ]

        with patch("backend.main.Sub2APIClient") as client_cls:
            client = client_cls.return_value
            client.groups = AsyncMock(return_value=[{"id": "g1", "name": "一组"}, {"id": "g2", "name": "二组"}])
            client.accounts = AsyncMock(return_value=accounts)
            resp = self.client.get("/api/admin/account-pool")

        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["summary"], {"group_count": 2, "account_count": 3, "allocated_count": 1, "unallocated_count": 2})
        self.assertEqual(data["groups"][0]["total"], 2)
        self.assertEqual(data["groups"][0]["allocated"], 1)
        self.assertEqual(data["groups"][1]["total"], 1)
        self.assertEqual(len(data["accounts"]), 3)
        used = next(account for account in data["accounts"] if account["id"] == "a1")
        self.assertEqual(used["groups"], [{"id": "g1", "name": "一组"}, {"id": "g2", "name": "二组"}])
        self.assertTrue(used["allocated"])
        self.assertEqual(used["allocation"]["card_code"], card["code"])
        ungrouped = next(account for account in data["accounts"] if account["id"] == "a3")
        self.assertEqual(ungrouped["groups"], [])
        self.assertNotIn("secret-token", resp.text)

    def test_admin_can_change_account_extraction_status_without_resetting_card(self):
        from backend.db import connect, create_batch, create_cards, mark_card_used

        conn = connect(backend_main.DB_PATH)
        try:
            batch = create_batch(conn, "状态切换")
            card = create_cards(
                conn,
                batch_id=batch["id"],
                group_id="g1",
                group_name="一组",
                account_count=1,
                generate_count=1,
                days=0,
                points=0,
            )[0]
            mark_card_used(conn, card["id"], "buyer-ip", [{"id": "a1", "name": "used@example.com"}])
        finally:
            conn.close()

        path = "/api/admin/account-pool/a1/extraction-status"
        without_csrf = self.client.put(path, json={"extracted": False, "account_name": "used@example.com"})
        self.assertEqual(without_csrf.status_code, 403, without_csrf.text)

        released = self.client.put(
            path,
            headers=self._headers(),
            json={"extracted": False, "account_name": "used@example.com"},
        )
        self.assertEqual(released.status_code, 200, released.text)
        self.assertFalse(released.json()["allocated"])

        conn = connect(backend_main.DB_PATH)
        try:
            self.assertEqual(conn.execute("SELECT status FROM cards WHERE id = ?", (card["id"],)).fetchone()["status"], "used")
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM account_allocations").fetchone()["count"], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM account_allocation_history").fetchone()["count"], 1)
        finally:
            conn.close()

        marked = self.client.put(
            path,
            headers=self._headers(),
            json={"extracted": True, "account_name": "used@example.com"},
        )
        self.assertEqual(marked.status_code, 200, marked.text)
        self.assertTrue(marked.json()["allocated"])
        self.assertTrue(marked.json()["manual_extracted"])

        accounts = [{"id": "a1", "name": "used@example.com", "status": "active", "groups": [{"id": "g1", "name": "一组"}]}]
        with patch("backend.main.Sub2APIClient") as client_cls:
            client = client_cls.return_value
            client.groups = AsyncMock(return_value=[{"id": "g1", "name": "一组"}])
            client.accounts = AsyncMock(return_value=accounts)
            pool = self.client.get("/api/admin/account-pool")

        self.assertEqual(pool.status_code, 200, pool.text)
        account = pool.json()["accounts"][0]
        self.assertTrue(account["allocated"])
        self.assertTrue(account["manual_extracted"])
        self.assertIsNone(account["allocation"])
        self.assertGreater(account["manual_extracted_at"], 0)

        conn = connect(backend_main.DB_PATH)
        try:
            audit = conn.execute(
                "SELECT action, target FROM admin_audit_logs WHERE action = 'set_account_extraction_status' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(audit)
            self.assertIn("account_id=a1", audit["target"])
        finally:
            conn.close()

    def test_stock_thresholds_and_check(self):
        resp = self.client.put(
            "/api/admin/settings/stock-thresholds",
            headers=self._headers(),
            json={"thresholds": [{"group_id": "g1", "group_name": "默认组", "min_available": 2, "enabled": True}]},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(self.client.get("/api/admin/settings/stock-thresholds").json()["settings"]["thresholds"][0]["min_available"], 2)

        with patch("backend.main.Sub2APIClient") as client_cls:
            client = client_cls.return_value
            client.accounts = AsyncMock(return_value=[{"id": "a1", "name": "a1@example.com"}])
            checked = self.client.post("/api/admin/stock/check", headers=self._headers())

        self.assertEqual(checked.status_code, 200, checked.text)
        warnings = checked.json()["stock"]["warnings"]
        self.assertEqual(warnings[0]["group_id"], "g1")
        self.assertEqual(warnings[0]["available"], 1)
        self.assertEqual(warnings[0]["min_available"], 2)

    def test_stock_check_counts_manual_extraction_in_its_current_group(self):
        from backend.db import connect, set_account_extracted

        saved = self.client.put(
            "/api/admin/settings/stock-thresholds",
            headers=self._headers(),
            json={"thresholds": [{"group_id": "g1", "group_name": "默认组", "min_available": 1, "enabled": True}]},
        )
        self.assertEqual(saved.status_code, 200, saved.text)

        conn = connect(backend_main.DB_PATH)
        try:
            set_account_extracted(conn, "a1", "a1@example.com", True)
        finally:
            conn.close()

        with patch("backend.main.Sub2APIClient") as client_cls:
            client = client_cls.return_value
            client.accounts = AsyncMock(return_value=[{"id": "a1", "name": "a1@example.com"}])
            checked = self.client.post("/api/admin/stock/check", headers=self._headers())

        self.assertEqual(checked.status_code, 200, checked.text)
        stock = checked.json()["stock"]
        self.assertEqual(stock["items"][0]["allocated"], 1)
        self.assertEqual(stock["items"][0]["available"], 0)

    def test_redeem_download_uses_full_exported_oauth_credentials(self):
        from backend.db import connect, create_batch, create_cards

        conn = connect(backend_main.DB_PATH)
        try:
            batch = create_batch(conn, "oauth export")
            card = create_cards(
                conn,
                batch_id=batch["id"],
                group_id="g1",
                group_name="team",
                account_count=1,
                generate_count=1,
                days=0,
                points=0,
            )[0]
        finally:
            conn.close()

        with patch("backend.main.Sub2APIClient") as client_cls:
            client = client_cls.return_value
            client.accounts = AsyncMock(
                return_value=[
                    {
                        "id": 3025,
                        "_sub2api_id": "3025",
                        "name": "oauth@example.com",
                        "credentials": {"email": "oauth@example.com"},
                    }
                ]
            )
            client.test_account = AsyncMock(return_value=(True, "ok"))
            client.export_accounts = AsyncMock(
                return_value=[
                    {
                        "name": "oauth@example.com",
                        "type": "oauth",
                        "credentials": {
                            "email": "oauth@example.com",
                            "access_token": "access-token-value",
                            "refresh_token": "refresh-token-value",
                            "id_token": "id-token-value",
                        },
                    }
                ]
            )
            resp = self.client.post("/api/redeem", json={"code": card["code"]})

        self.assertEqual(resp.status_code, 200, resp.text)
        with ZipFile(BytesIO(resp.content)) as zf:
            sub2api = json.loads(zf.read("sub2api.json"))
            cpa = json.loads(zf.read("cpa.json"))
        self.assertEqual(sub2api["accounts"][0]["credentials"]["access_token"], "access-token-value")
        self.assertEqual(sub2api["accounts"][0]["credentials"]["refresh_token"], "refresh-token-value")
        self.assertEqual(cpa[0]["access_token"], "access-token-value")
        log = self.client.get(f"/api/admin/logs?card_id={card['id']}").json()["logs"][0]
        self.assertEqual(log["message"], "1 个账号")

    def test_security_center_lists_failures_audit_and_abnormal_ips(self):
        from backend.db import connect, log_access, log_admin_audit, record_login_failure

        conn = connect(backend_main.DB_PATH)
        try:
            for _ in range(5):
                record_login_failure(conn, "8.8.8.8:admin", now=int(time.time()))
            for _ in range(8):
                log_access(conn, None, "9.9.9.9", "ua", "invalid", "bad")
            log_admin_audit(conn, actor_id=1, actor_username="admin", action="change_password", target="user_id=1", ip="7.7.7.7", result="ok")
        finally:
            conn.close()

        summary = self.client.get("/api/admin/security/summary")
        self.assertEqual(summary.status_code, 200, summary.text)
        abnormal_ips = {item["ip"] for item in summary.json()["abnormal_ips"]}
        self.assertIn("8.8.8.8", abnormal_ips)
        self.assertIn("9.9.9.9", abnormal_ips)

        audits = self.client.get("/api/admin/security/audit-logs?limit=10")
        self.assertEqual(audits.status_code, 200, audits.text)
        self.assertTrue(any(row["action"] == "change_password" for row in audits.json()["logs"]))

        failures = self.client.get("/api/admin/security/login-failures?limit=10")
        self.assertEqual(failures.status_code, 200, failures.text)
        self.assertEqual(failures.json()["failures"][0]["failures"], 5)

    def test_smtp_settings_do_not_expose_password_and_test_mail_is_audited(self):
        payload = {
            "enabled": True,
            "host": "smtp.example.com",
            "port": 465,
            "username": "notice@example.com",
            "password": "smtp-secret",
            "from_email": "notice@example.com",
            "to_email": "owner@example.com",
            "use_ssl": True,
            "use_tls": False,
        }
        saved = self.client.put("/api/admin/settings/smtp", headers=self._headers(), json=payload)
        self.assertEqual(saved.status_code, 200, saved.text)

        settings = self.client.get("/api/admin/settings/smtp")
        self.assertEqual(settings.status_code, 200, settings.text)
        self.assertTrue(settings.json()["settings"]["has_password"])
        self.assertNotIn("smtp-secret", settings.text)

        with patch("smtplib.SMTP_SSL") as smtp_ssl:
            test_resp = self.client.post("/api/admin/settings/smtp/test", headers=self._headers())
        self.assertEqual(test_resp.status_code, 200, test_resp.text)
        smtp_ssl.assert_called_once()
        audits = self.client.get("/api/admin/security/audit-logs?limit=10")
        self.assertTrue(any(row["action"] == "smtp_test" for row in audits.json()["logs"]))

    def test_access_logs_can_filter_and_bulk_delete(self):
        from backend.db import connect, log_access

        conn = connect(backend_main.DB_PATH)
        try:
            log_access(conn, None, "1.1.1.1", "ua-a", "not_found", "sha256:hidden-a")
            log_access(conn, None, "2.2.2.2", "ua-b", "invalid", "INVALID-CODE")
        finally:
            conn.close()

        filtered = self.client.get("/api/admin/logs?keyword=hidden-a&result=not_found")
        self.assertEqual(filtered.status_code, 200, filtered.text)
        logs = filtered.json()["logs"]
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["ip"], "1.1.1.1")

        deleted = self.client.post("/api/admin/logs/bulk-delete", headers=self._headers(), json={"ids": [logs[0]["id"]]})
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["deleted"], 1)
        after = self.client.get("/api/admin/logs?keyword=hidden-a")
        self.assertEqual(after.json()["logs"], [])

    def test_batches_can_delete_without_deleting_cards(self):
        batch, cards = self._seed_cards()

        resp = self.client.post("/api/admin/batches/bulk-delete", headers=self._headers(), json={"ids": [batch["id"]]})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["deleted"], 1)

        from backend.db import connect

        conn = connect(backend_main.DB_PATH)
        try:
            batch_rows = conn.execute("SELECT COUNT(*) FROM batches WHERE id = ?", (batch["id"],)).fetchone()[0]
            card_rows = conn.execute("SELECT COUNT(*) FROM cards WHERE id IN (?, ?, ?)", tuple(card["id"] for card in cards)).fetchone()[0]
            unbatched = conn.execute("SELECT COUNT(*) FROM cards WHERE batch_id IS NULL").fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(batch_rows, 0)
        self.assertEqual(card_rows, 3)
        self.assertEqual(unbatched, 3)


if __name__ == "__main__":
    unittest.main()
