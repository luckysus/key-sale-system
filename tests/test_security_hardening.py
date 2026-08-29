import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend import db as database
from backend.db import (
    allocated_ids,
    connect,
    create_batch,
    create_cards,
    create_session,
    clear_login_failures,
    ensure_admin,
    get_session_user,
    init_db,
    is_login_locked,
    list_account_allocations,
    mark_card_used,
    record_login_failure,
    session_key,
    set_card_status,
)
from backend.security import RateLimiter, same_origin_allowed


class SecurityHardeningTest(unittest.TestCase):
    def test_rate_limiter_blocks_after_limit_inside_window(self):
        limiter = RateLimiter()
        self.assertTrue(limiter.allow("ip:1", 2, 60, now=100))
        self.assertTrue(limiter.allow("ip:1", 2, 60, now=101))
        self.assertFalse(limiter.allow("ip:1", 2, 60, now=102))
        self.assertTrue(limiter.allow("ip:1", 2, 60, now=162))

    def test_same_origin_rejects_cross_origin(self):
        self.assertTrue(same_origin_allowed("admin.example.com", "https://admin.example.com"))
        self.assertFalse(same_origin_allowed("admin.example.com", "https://evil.example"))

    def test_session_is_stored_hashed_and_still_authenticates(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "app.sqlite")
            init_db(conn)
            ensure_admin(conn, "admin", "secret-pass")
            token = create_session(conn, 1)
            stored = conn.execute("SELECT token FROM sessions").fetchone()["token"]
            self.assertEqual(stored, session_key(token))
            self.assertNotEqual(stored, token)
            self.assertEqual(get_session_user(conn, token)["username"], "admin")
            conn.close()

    def test_used_card_cannot_be_reenabled_or_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "app.sqlite")
            init_db(conn)
            batch = create_batch(conn, "安全测试")
            [card] = create_cards(
                conn,
                batch_id=batch["id"],
                group_id="g1",
                group_name="默认组",
                account_count=1,
                generate_count=1,
                days=0,
                points=0,
            )
            mark_card_used(conn, card["id"], "tester", [{"id": "a1", "name": "a"}])
            with self.assertRaisesRegex(ValueError, "已使用卡密不能变更状态"):
                set_card_status(conn, card["id"], "disabled")
            conn.close()

    def test_mark_card_used_is_atomic_for_repeated_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "app.sqlite")
            conn.row_factory = sqlite3.Row
            init_db(conn)
            batch = create_batch(conn, "并发保护")
            [card] = create_cards(
                conn,
                batch_id=batch["id"],
                group_id="g1",
                group_name="默认组",
                account_count=1,
                generate_count=1,
                days=0,
                points=0,
            )
            mark_card_used(conn, card["id"], "first", [{"id": "a1", "name": "a"}])
            with self.assertRaisesRegex(ValueError, "卡密已使用或不可用"):
                mark_card_used(conn, card["id"], "second", [{"id": "a2", "name": "b"}])
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM account_allocations").fetchone()["count"], 1)
            conn.close()

    def test_released_account_can_be_sold_again_without_losing_card_history(self):
        set_account_extracted = getattr(database, "set_account_extracted", None)
        self.assertIsNotNone(set_account_extracted, "缺少账号提取状态切换函数")

        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "app.sqlite")
            init_db(conn)
            batch = create_batch(conn, "重复出售")
            first_card, second_card = create_cards(
                conn,
                batch_id=batch["id"],
                group_id="g1",
                group_name="默认组",
                account_count=1,
                generate_count=2,
                days=0,
                points=0,
            )

            mark_card_used(conn, first_card["id"], "first", [{"id": "a1", "name": "account@example.com"}])
            set_account_extracted(conn, "a1", "account@example.com", False)

            self.assertNotIn("a1", allocated_ids(conn))
            self.assertEqual(conn.execute("SELECT status FROM cards WHERE id = ?", (first_card["id"],)).fetchone()["status"], "used")
            self.assertEqual([row["sub2api_account_id"] for row in list_account_allocations(conn, first_card["id"])], ["a1"])

            mark_card_used(conn, second_card["id"], "second", [{"id": "a1", "name": "account@example.com"}])

            self.assertIn("a1", allocated_ids(conn))
            self.assertEqual([row["sub2api_account_id"] for row in list_account_allocations(conn, first_card["id"])], ["a1"])
            self.assertEqual([row["sub2api_account_id"] for row in list_account_allocations(conn, second_card["id"])], ["a1"])
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM account_allocation_history").fetchone()["count"], 2)
            conn.close()

    def test_login_failures_lock_until_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "app.sqlite")
            init_db(conn)
            key = "203.0.113.10:admin"
            for _ in range(5):
                record_login_failure(conn, key, max_attempts=5, lock_seconds=900, now=100)
            self.assertTrue(is_login_locked(conn, key, now=101))
            clear_login_failures(conn, key)
            self.assertFalse(is_login_locked(conn, key, now=102))
            conn.close()

    def test_cleanup_security_state_applies_retention_windows(self):
        cleanup = getattr(database, "cleanup_security_state", None)
        self.assertTrue(callable(cleanup), "cleanup_security_state is missing")
        day = 86400
        now = 200 * day
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "app.sqlite")
            init_db(conn)
            ensure_admin(conn, "admin", "secret-pass")
            conn.executemany(
                "INSERT INTO sessions (token, user_id, expires_at, created_at) VALUES (?, 1, ?, ?)",
                [("expired", now, now - day), ("active", now + day, now)],
            )
            conn.executemany(
                "INSERT INTO login_failures (key, failures, locked_until, updated_at) VALUES (?, 1, 0, ?)",
                [("old", now - 31 * day), ("new", now - 29 * day)],
            )
            conn.executemany(
                "INSERT INTO admin_audit_logs (actor_username, action, created_at) VALUES ('admin', 'test', ?)",
                [(now - 181 * day,), (now - 179 * day,)],
            )
            conn.commit()

            self.assertEqual(cleanup(conn, now=now), {"sessions": 1, "login_failures": 1, "audit_logs": 1})
            self.assertEqual(conn.execute("SELECT token FROM sessions").fetchone()["token"], "active")
            self.assertEqual(conn.execute("SELECT key FROM login_failures").fetchone()["key"], "new")
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM admin_audit_logs").fetchone()["count"], 1)
            conn.close()


if __name__ == "__main__":
    unittest.main()
