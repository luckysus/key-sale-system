import json
import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .security import hash_password, now_ts, token


CARD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
DUMMY_PASSWORD_HASH = hash_password("invalid-password-placeholder", b"\0" * 16)


def session_key(session_token: str) -> str:
    return "sha256:" + hashlib.sha256(session_token.encode("utf-8")).hexdigest()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            email TEXT NOT NULL DEFAULT '',
            avatar TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES admin_users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            batch_id INTEGER,
            group_id TEXT NOT NULL,
            group_name TEXT NOT NULL,
            account_count INTEGER NOT NULL,
            points INTEGER NOT NULL DEFAULT 0,
            days INTEGER NOT NULL DEFAULT 30,
            status TEXT NOT NULL DEFAULT 'unused',
            used_by TEXT NOT NULL DEFAULT '',
            used_at INTEGER,
            expires_at INTEGER,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY(batch_id) REFERENCES batches(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS card_access_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id INTEGER,
            ip TEXT NOT NULL,
            user_agent TEXT NOT NULL,
            result TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            FOREIGN KEY(card_id) REFERENCES cards(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS account_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id INTEGER NOT NULL,
            sub2api_account_id TEXT NOT NULL,
            account_name TEXT NOT NULL DEFAULT '',
            test_status TEXT NOT NULL DEFAULT '',
            allocated_at INTEGER NOT NULL,
            FOREIGN KEY(card_id) REFERENCES cards(id) ON DELETE CASCADE,
            UNIQUE(sub2api_account_id)
        );

        CREATE TABLE IF NOT EXISTS account_allocation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_allocation_id INTEGER NOT NULL UNIQUE,
            card_id INTEGER,
            card_code TEXT NOT NULL DEFAULT '',
            sub2api_account_id TEXT NOT NULL,
            account_name TEXT NOT NULL DEFAULT '',
            test_status TEXT NOT NULL DEFAULT '',
            allocated_at INTEGER NOT NULL,
            FOREIGN KEY(card_id) REFERENCES cards(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS manual_extracted_accounts (
            sub2api_account_id TEXT PRIMARY KEY,
            account_name TEXT NOT NULL DEFAULT '',
            extracted_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS admin_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER,
            actor_username TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            target TEXT NOT NULL DEFAULT '',
            ip TEXT NOT NULL DEFAULT '',
            result TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS login_failures (
            key TEXT PRIMARY KEY,
            failures INTEGER NOT NULL DEFAULT 0,
            locked_until INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL
        );
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO account_allocation_history
          (source_allocation_id, card_id, card_code, sub2api_account_id, account_name, test_status, allocated_at)
        SELECT a.id, a.card_id, c.code, a.sub2api_account_id, a.account_name, a.test_status, a.allocated_at
        FROM account_allocations a
        JOIN cards c ON c.id = a.card_id
        """
    )
    conn.commit()


def rowdict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    return dict(row) if row else None


def ensure_admin(conn: sqlite3.Connection, username: str, password: str) -> bool:
    if conn.execute("SELECT id FROM admin_users LIMIT 1").fetchone():
        return False
    conn.execute(
        "INSERT INTO admin_users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, hash_password(password), now_ts()),
    )
    conn.commit()
    return True


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM admin_users WHERE username = ?", (username,)).fetchone()
    from .security import verify_password

    if not row:
        verify_password(password, DUMMY_PASSWORD_HASH)
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return public_user(row)


def is_login_locked(conn: sqlite3.Connection, key: str, now: Optional[int] = None) -> bool:
    ts = now_ts() if now is None else int(now)
    row = conn.execute("SELECT locked_until FROM login_failures WHERE key = ?", (key,)).fetchone()
    return bool(row and int(row["locked_until"] or 0) > ts)


def record_login_failure(
    conn: sqlite3.Connection,
    key: str,
    *,
    max_attempts: int = 5,
    lock_seconds: int = 900,
    now: Optional[int] = None,
) -> None:
    ts = now_ts() if now is None else int(now)
    row = conn.execute("SELECT failures, locked_until FROM login_failures WHERE key = ?", (key,)).fetchone()
    if row and int(row["locked_until"] or 0) > ts:
        failures = int(row["failures"] or 0)
        locked_until = int(row["locked_until"] or 0)
    else:
        failures = (int(row["failures"] or 0) if row else 0) + 1
        locked_until = ts + int(lock_seconds) if failures >= int(max_attempts) else 0
    conn.execute(
        """
        INSERT INTO login_failures (key, failures, locked_until, updated_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            failures = excluded.failures,
            locked_until = excluded.locked_until,
            updated_at = excluded.updated_at
        """,
        (key, failures, locked_until, ts),
    )
    conn.commit()


def clear_login_failures(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("DELETE FROM login_failures WHERE key = ?", (key,))
    conn.commit()


def cleanup_security_state(conn: sqlite3.Connection, now: Optional[int] = None) -> dict[str, int]:
    ts = now_ts() if now is None else int(now)
    counts = {
        "sessions": conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (ts,)).rowcount,
        "login_failures": conn.execute(
            "DELETE FROM login_failures WHERE updated_at < ?", (ts - 30 * 86400,)
        ).rowcount,
        "audit_logs": conn.execute(
            "DELETE FROM admin_audit_logs WHERE created_at < ?", (ts - 180 * 86400,)
        ).rowcount,
    }
    conn.commit()
    return counts


def public_user(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "username": row["username"], "email": row["email"], "avatar": row["avatar"]}


def create_session(conn: sqlite3.Connection, user_id: int, ttl_seconds: int = 604800) -> str:
    value = token()
    ts = now_ts()
    conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
        (session_key(value), user_id, ts + ttl_seconds, ts),
    )
    conn.commit()
    return value


def get_session_user(conn: sqlite3.Connection, session_token: Optional[str]) -> Optional[dict[str, Any]]:
    if not session_token:
        return None
    row = conn.execute(
        """
        SELECT u.* FROM sessions s
        JOIN admin_users u ON u.id = s.user_id
        WHERE s.token IN (?, ?) AND s.expires_at > ?
        """,
        (session_key(session_token), session_token, now_ts()),
    ).fetchone()
    return public_user(row) if row else None


def delete_session(conn: sqlite3.Connection, session_token: Optional[str]) -> None:
    if session_token:
        conn.execute("DELETE FROM sessions WHERE token IN (?, ?)", (session_key(session_token), session_token))
        conn.commit()


def get_setting(conn: sqlite3.Connection, key: str) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else None


def put_setting(conn: sqlite3.Connection, key: str, value: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, json.dumps(value, ensure_ascii=False, separators=(",", ":")), now_ts()),
    )
    conn.commit()


def generate_card_code() -> str:
    import secrets

    return "-".join("".join(secrets.choice(CARD_ALPHABET) for _ in range(4)) for _ in range(4))


def create_batch(conn: sqlite3.Connection, name: str, note: str = "") -> dict[str, Any]:
    clean = str(name or "").strip()
    if not clean:
        raise ValueError("批次名称不能为空")
    cur = conn.execute(
        "INSERT INTO batches (name, note, created_at) VALUES (?, ?, ?)",
        (clean, str(note or ""), now_ts()),
    )
    conn.commit()
    return rowdict(conn.execute("SELECT * FROM batches WHERE id = ?", (cur.lastrowid,)).fetchone()) or {}


def list_batches(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute("SELECT * FROM batches ORDER BY id DESC")]


def delete_batch(conn: sqlite3.Connection, batch_id: int) -> bool:
    cur = conn.execute("DELETE FROM batches WHERE id = ?", (int(batch_id),))
    conn.commit()
    return bool(cur.rowcount)


def bulk_delete_batches(conn: sqlite3.Connection, ids: list[int]) -> int:
    clean_ids = sorted({int(item) for item in ids if int(item) > 0})
    if not clean_ids:
        return 0
    placeholders = ",".join("?" for _ in clean_ids)
    cur = conn.execute(f"DELETE FROM batches WHERE id IN ({placeholders})", clean_ids)
    conn.commit()
    return int(cur.rowcount or 0)


def list_cards(
    conn: sqlite3.Connection,
    limit: int = 500,
    *,
    status: str = "",
    batch_id: Optional[int] = None,
    group_id: str = "",
    keyword: str = "",
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if status and status != "all":
        where.append("c.status = ?")
        params.append(status)
    if batch_id:
        where.append("c.batch_id = ?")
        params.append(int(batch_id))
    if group_id:
        where.append("c.group_id = ?")
        params.append(str(group_id))
    if keyword:
        like = f"%{keyword}%"
        where.append("(c.code LIKE ? OR c.group_name LIKE ? OR c.used_by LIKE ? OR b.name LIKE ?)")
        params.extend([like, like, like, like])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    params.append(max(1, min(int(limit), 5000)))
    return [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT c.*, b.name AS batch_name
            FROM cards c
            LEFT JOIN batches b ON b.id = c.batch_id
            {where_sql}
            ORDER BY c.id DESC LIMIT ?
            """,
            params,
        )
    ]


def get_card(conn: sqlite3.Connection, card_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute(
        """
        SELECT c.*, b.name AS batch_name
        FROM cards c
        LEFT JOIN batches b ON b.id = c.batch_id
        WHERE c.id = ?
        """,
        (int(card_id),),
    ).fetchone()
    return rowdict(row)


def list_access_logs(
    conn: sqlite3.Connection,
    limit: int = 500,
    card_id: Optional[int] = None,
    *,
    result: str = "",
    keyword: str = "",
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where_parts: list[str] = []
    if card_id:
        where_parts.append("l.card_id = ?")
        params.append(card_id)
    if result and result != "all":
        where_parts.append("l.result = ?")
        params.append(result)
    if keyword:
        like = f"%{keyword}%"
        where_parts.append("(c.code LIKE ? OR l.ip LIKE ? OR l.user_agent LIKE ? OR l.message LIKE ? OR l.result LIKE ?)")
        params.extend([like, like, like, like, like])
    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    params.append(max(1, min(int(limit), 5000)))
    return [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT l.*, c.code AS card_code
            FROM card_access_logs l
            LEFT JOIN cards c ON c.id = l.card_id
            {where}
            ORDER BY l.id DESC LIMIT ?
            """,
            params,
        )
    ]


def bulk_delete_access_logs(conn: sqlite3.Connection, ids: list[int]) -> int:
    clean_ids = sorted({int(item) for item in ids if int(item) > 0})
    if not clean_ids:
        return 0
    placeholders = ",".join("?" for _ in clean_ids)
    cur = conn.execute(f"DELETE FROM card_access_logs WHERE id IN ({placeholders})", clean_ids)
    conn.commit()
    return int(cur.rowcount or 0)


def list_account_allocations(conn: sqlite3.Connection, card_id: int) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, card_id, sub2api_account_id, account_name, test_status, allocated_at
            FROM account_allocation_history
            WHERE card_id = ?
            UNION ALL
            SELECT a.id, a.card_id, a.sub2api_account_id, a.account_name, a.test_status, a.allocated_at
            FROM account_allocations a
            WHERE a.card_id = ?
              AND NOT EXISTS (
                SELECT 1 FROM account_allocation_history h WHERE h.source_allocation_id = a.id
              )
            ORDER BY allocated_at DESC, id DESC
            """,
            (int(card_id), int(card_id)),
        )
    ]


def create_cards(
    conn: sqlite3.Connection,
    *,
    batch_id: Optional[int],
    group_id: str,
    group_name: str,
    account_count: int,
    generate_count: int,
    days: int,
    points: int,
) -> list[dict[str, Any]]:
    if account_count < 1 or generate_count < 1:
        raise ValueError("账号数量和卡密数量至少为 1")
    ts = now_ts()
    expires_at = ts + int(days) * 86400 if days else None
    created = []
    for _ in range(generate_count):
        code = generate_card_code()
        while conn.execute("SELECT 1 FROM cards WHERE code = ?", (code,)).fetchone():
            code = generate_card_code()
        cur = conn.execute(
            """
            INSERT INTO cards
              (code, batch_id, group_id, group_name, account_count, points, days, expires_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (code, batch_id, group_id, group_name, account_count, points, days, expires_at, ts, ts),
        )
        created.append(rowdict(conn.execute("SELECT * FROM cards WHERE id = ?", (cur.lastrowid,)).fetchone()))
    conn.commit()
    return [card for card in created if card]


def set_card_status(conn: sqlite3.Connection, card_id: int, status: str) -> dict[str, Any]:
    if status not in {"unused", "disabled"}:
        raise ValueError("状态只能设置为 unused 或 disabled")
    current = conn.execute("SELECT status FROM cards WHERE id = ?", (card_id,)).fetchone()
    if not current:
        raise ValueError("卡密不存在")
    if current["status"] == "used":
        raise ValueError("已使用卡密不能变更状态")
    conn.execute("UPDATE cards SET status = ?, updated_at = ? WHERE id = ?", (status, now_ts(), card_id))
    conn.commit()
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    return dict(row)


def bulk_set_card_status(conn: sqlite3.Connection, ids: list[int], status: str) -> int:
    if status not in {"unused", "disabled"}:
        raise ValueError("状态只能设置为 unused 或 disabled")
    clean_ids = sorted({int(item) for item in ids if int(item) > 0})
    if not clean_ids:
        return 0
    placeholders = ",".join("?" for _ in clean_ids)
    used = conn.execute(f"SELECT COUNT(*) AS count FROM cards WHERE id IN ({placeholders}) AND status = 'used'", clean_ids).fetchone()
    if used and int(used["count"] or 0):
        raise ValueError("已使用卡密不能变更状态")
    ts = now_ts()
    cur = conn.execute(f"UPDATE cards SET status = ?, updated_at = ? WHERE id IN ({placeholders})", [status, ts, *clean_ids])
    conn.commit()
    return int(cur.rowcount or 0)


def allocated_ids(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row["sub2api_account_id"])
        for row in conn.execute(
            """
            SELECT sub2api_account_id FROM account_allocations
            UNION
            SELECT sub2api_account_id FROM manual_extracted_accounts
            """
        )
    }


def manual_extracted_accounts(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {
        str(row["sub2api_account_id"]): dict(row)
        for row in conn.execute(
            "SELECT sub2api_account_id, account_name, extracted_at FROM manual_extracted_accounts"
        )
    }


def set_account_extracted(
    conn: sqlite3.Connection,
    account_id: str,
    account_name: str,
    extracted: bool,
) -> dict[str, Any]:
    account_id = str(account_id).strip()
    account_name = str(account_name).strip()
    if not account_id:
        raise ValueError("账号 ID 不能为空")

    current = conn.execute(
        "SELECT allocated_at FROM account_allocations WHERE sub2api_account_id = ?",
        (account_id,),
    ).fetchone()
    if extracted and current:
        conn.execute("DELETE FROM manual_extracted_accounts WHERE sub2api_account_id = ?", (account_id,))
        conn.commit()
        return {"allocated": True, "manual_extracted": False, "manual_extracted_at": None}

    if extracted:
        extracted_at = now_ts()
        conn.execute(
            """
            INSERT INTO manual_extracted_accounts (sub2api_account_id, account_name, extracted_at)
            VALUES (?, ?, ?)
            ON CONFLICT(sub2api_account_id) DO UPDATE SET
              account_name = excluded.account_name,
              extracted_at = excluded.extracted_at
            """,
            (account_id, account_name, extracted_at),
        )
        conn.commit()
        return {"allocated": True, "manual_extracted": True, "manual_extracted_at": extracted_at}

    conn.execute("DELETE FROM account_allocations WHERE sub2api_account_id = ?", (account_id,))
    conn.execute("DELETE FROM manual_extracted_accounts WHERE sub2api_account_id = ?", (account_id,))
    conn.commit()
    return {"allocated": False, "manual_extracted": False, "manual_extracted_at": None}


def allocated_ids_for_group(conn: sqlite3.Connection, group_id: str) -> set[str]:
    return {
        str(row["sub2api_account_id"])
        for row in conn.execute(
            """
            SELECT a.sub2api_account_id
            FROM account_allocations a
            JOIN cards c ON c.id = a.card_id
            WHERE c.group_id = ?
            """,
            (str(group_id),),
        )
    }


def mark_card_used(conn: sqlite3.Connection, card_id: int, used_by: str, accounts: list[dict[str, Any]]) -> None:
    ts = now_ts()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "UPDATE cards SET status = 'used', used_by = ?, used_at = ?, updated_at = ? WHERE id = ? AND status = 'unused'",
            (used_by, ts, ts, card_id),
        )
        if cur.rowcount != 1:
            raise ValueError("卡密已使用或不可用")
        card_code = str(conn.execute("SELECT code FROM cards WHERE id = ?", (card_id,)).fetchone()["code"])
        inserted = 0
        for account in accounts:
            account_id = str(account.get("_sub2api_id") or account.get("id") or account.get("name") or "")
            account_name = str(account.get("name") or account.get("email") or "")
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO account_allocations
                  (card_id, sub2api_account_id, account_name, test_status, allocated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    card_id,
                    account_id,
                    account_name,
                    "alive",
                    ts,
                ),
            )
            inserted += cur.rowcount
            if cur.rowcount:
                conn.execute(
                    """
                    INSERT INTO account_allocation_history
                      (source_allocation_id, card_id, card_code, sub2api_account_id, account_name, test_status, allocated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (cur.lastrowid, card_id, card_code, account_id, account_name, "alive", ts),
                )
                conn.execute("DELETE FROM manual_extracted_accounts WHERE sub2api_account_id = ?", (account_id,))
        if inserted != len(accounts):
            raise ValueError("账号已被分配，请重试")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def log_access(conn: sqlite3.Connection, card_id: Optional[int], ip: str, user_agent: str, result: str, message: str = "") -> None:
    conn.execute(
        "INSERT INTO card_access_logs (card_id, ip, user_agent, result, message, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (card_id, ip, user_agent, result, message, now_ts()),
    )
    conn.commit()


def log_admin_audit(
    conn: sqlite3.Connection,
    *,
    actor_id: Optional[int],
    actor_username: str,
    action: str,
    target: str = "",
    ip: str = "",
    result: str = "ok",
) -> None:
    """记录后台写操作审计日志。调用方需确保不传入明文密码、完整卡密码、sub2api 密钥等敏感信息。"""
    conn.execute(
        "INSERT INTO admin_audit_logs (actor_id, actor_username, action, target, ip, result, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            actor_id,
            (actor_username or "")[:80],
            (action or "")[:60],
            (target or "")[:200],
            (ip or "")[:64],
            (result or "")[:60],
            now_ts(),
        ),
    )
    conn.commit()


def list_admin_audit_logs(conn: sqlite3.Connection, limit: int = 500) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute("SELECT * FROM admin_audit_logs ORDER BY id DESC LIMIT ?", (int(limit),))]


def list_login_failures(conn: sqlite3.Connection, limit: int = 500) -> list[dict[str, Any]]:
    rows = []
    for row in conn.execute("SELECT * FROM login_failures ORDER BY updated_at DESC LIMIT ?", (int(limit),)):
        item = dict(row)
        key = str(item.get("key") or "")
        item["ip"] = key.split(":", 1)[0] if ":" in key else key
        item["username"] = key.split(":", 1)[1] if ":" in key else ""
        rows.append(item)
    return rows


def card_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) AS count FROM cards GROUP BY status").fetchall()
    counts = {str(row["status"]): int(row["count"] or 0) for row in rows}
    total = sum(counts.values())
    return {
        "total_cards": total,
        "unused_cards": counts.get("unused", 0),
        "used_cards": counts.get("used", 0),
        "disabled_cards": counts.get("disabled", 0),
    }
