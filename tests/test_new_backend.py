import json
import tempfile
import threading
import unittest
import asyncio
from pathlib import Path
from zipfile import ZipFile

from backend.converter import build_accounts_zip
from backend.db import connect, create_batch, create_cards, init_db, list_batches
from backend.sub2api_client import Sub2APIClient, Sub2APISettings


class NewBackendTest(unittest.TestCase):
    def test_card_generation_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "app.sqlite")
            init_db(conn)
            batch = create_batch(conn, "测试批次")
            cards = create_cards(
                conn,
                batch_id=batch["id"],
                group_id="g1",
                group_name="默认组",
                account_count=2,
                generate_count=3,
                days=30,
                points=3000,
            )
            self.assertEqual(len(cards), 3)
            self.assertEqual(cards[0]["status"], "unused")
            self.assertEqual(cards[0]["account_count"], 2)
            conn.close()

    def test_sqlite_connection_can_close_from_worker_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "app.sqlite")
            init_db(conn)
            create_batch(conn, "thread check")
            errors = []

            def worker():
                try:
                    self.assertEqual(len(list_batches(conn)), 1)
                    conn.close()
                except Exception as exc:
                    errors.append(exc)

            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()
            self.assertEqual(errors, [])

    def test_zip_contains_only_sub2api_and_cpa_json(self):
        content = build_accounts_zip(
            "AAAA-BBBB-CCCC-DDDD",
            [{"id": 1, "name": "a@example.com", "credentials": {"access_token": "at"}}],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.zip"
            path.write_bytes(content)
            with ZipFile(path) as zf:
                self.assertEqual(sorted(zf.namelist()), ["cpa.json", "sub2api.json"])
                sub2api = json.loads(zf.read("sub2api.json"))
                cpa = json.loads(zf.read("cpa.json"))
            self.assertEqual(sub2api["accounts"][0]["name"], "a@example.com")
            self.assertEqual(cpa[0]["access_token"], "at")

    def test_sub2api_accounts_use_admin_list_id_for_liveness(self):
        async def run():
            client = Sub2APIClient(Sub2APISettings("http://example.test"))

            async def fake_json(method, path, *, params=None, json_body=None):
                self.assertEqual(path, "/api/v1/admin/accounts")
                self.assertEqual(params["group"], "8")
                return {"items": [{"id": 3025, "name": "a@example.com"}]}

            client._json = fake_json
            accounts = await client.accounts("8")
            self.assertEqual(accounts[0]["_sub2api_id"], "3025")

        asyncio.run(run())

    def test_sub2api_test_account_uses_api_route(self):
        async def run():
            client = Sub2APIClient(Sub2APISettings("http://example.test"))
            paths = []

            async def fake_test_once(path, prefer_bearer):
                paths.append(path)
                return True, "ok"

            client._test_account_once = fake_test_once
            ok, _ = await client.test_account("3025")
            self.assertTrue(ok)
            self.assertEqual(paths, ["/api/v1/admin/accounts/3025/test"])

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
