import json
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote

import httpx


@dataclass
class Sub2APISettings:
    base_url: str
    api_key: str = ""
    bearer_token: str = ""


def normalize_base_url(value: str) -> str:
    clean = str(value or "").strip().rstrip("/")
    if not clean:
        raise ValueError("请先配置 sub2api 地址")
    return clean


class Sub2APIClient:
    def __init__(self, settings: Sub2APISettings):
        self.base_url = normalize_base_url(settings.base_url)
        self.api_key = settings.api_key.strip()
        self.bearer_token = settings.bearer_token.strip()

    def _headers(self, prefer_bearer: bool = False) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if prefer_bearer and self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        elif self.api_key:
            headers["x-api-key"] = self.api_key
        elif self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        return headers

    async def _json(self, method: str, path: str, *, params: Optional[dict[str, Any]] = None, json_body: Optional[dict] = None) -> Any:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                json=json_body,
                headers={**self._headers(), "Content-Type": "application/json"},
            )
        payload = response.json() if response.content else {}
        if response.status_code >= 400:
            raise ValueError(payload.get("message") or payload.get("detail") or f"sub2api HTTP {response.status_code}")
        if isinstance(payload, dict) and payload.get("code") not in (None, 0, "0"):
            raise ValueError(payload.get("message") or payload.get("msg") or "sub2api 返回错误")
        return payload.get("data") if isinstance(payload, dict) and "data" in payload else payload

    async def groups(self) -> list[dict[str, Any]]:
        payload = await self._json("GET", "/api/v1/admin/groups/all")
        groups = payload if isinstance(payload, list) else payload.get("groups") or payload.get("items") or []
        return [
            {"id": str(group.get("id") or group.get("group_id")), "name": group.get("name") or group.get("group_name") or str(group.get("id"))}
            for group in groups
            if group.get("id") is not None or group.get("group_id") is not None
        ]

    async def accounts(self, group_id: str = "") -> list[dict[str, Any]]:
        params = {"page_size": "1000"}
        if group_id:
            params["group"] = group_id
        payload = await self._json(
            "GET",
            "/api/v1/admin/accounts",
            params=params,
        )
        accounts = payload if isinstance(payload, list) else payload.get("accounts") or payload.get("items") or []
        if not isinstance(accounts, list):
            raise ValueError("无法识别 sub2api 账号返回格式")
        for account in accounts:
            account["_sub2api_id"] = str(account.get("id") or account.get("account_id") or account.get("name") or "")
        return accounts

    async def export_accounts(self) -> list[dict[str, Any]]:
        payload = await self._json("GET", "/api/v1/admin/accounts/data")
        accounts = payload if isinstance(payload, list) else payload.get("accounts") or payload.get("items") or []
        if not isinstance(accounts, list):
            raise ValueError("无法识别 sub2api 账号导出返回格式")
        return accounts

    async def test_account(self, account_id: str) -> tuple[bool, str]:
        if not account_id:
            return False, "missing account id"
        paths = [f"/api/v1/admin/accounts/{quote(account_id, safe='')}/test"]
        auth_modes = [True, False] if self.bearer_token and self.api_key else [bool(self.bearer_token)]
        last_error = ""
        for path in paths:
            for prefer_bearer in auth_modes:
                ok, message = await self._test_account_once(path, prefer_bearer)
                if ok:
                    return True, message
                last_error = message
        return False, last_error or "test failed"

    async def _test_account_once(self, path: str, prefer_bearer: bool) -> tuple[bool, str]:
        headers = {**self._headers(prefer_bearer=prefer_bearer), "Content-Type": "application/json"}
        body = {"prompt": "Reply OK if this account is available.", "mode": "default"}
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream("POST", f"{self.base_url}{path}", headers=headers, json=body) as response:
                    if response.status_code >= 400:
                        text = await response.aread()
                        return False, text.decode("utf-8", "ignore")[:300] or f"HTTP {response.status_code}"
                    seen_complete = False
                    async for line in response.aiter_lines():
                        parsed = parse_stream_event(line)
                        if not parsed:
                            continue
                        if parsed.get("type") == "test_complete":
                            seen_complete = True
                            if parsed.get("success") is True:
                                return True, parsed.get("message") or "test_complete success"
                            return False, parsed.get("error") or parsed.get("message") or "test_complete failed"
                    return False, "no test_complete event" if not seen_complete else "test failed"
        except Exception as exc:
            return False, str(exc)


def parse_stream_event(line: str) -> Optional[dict[str, Any]]:
    clean = str(line or "").strip()
    if not clean:
        return None
    if clean.startswith("data:"):
        clean = clean[5:].strip()
    if not clean or clean == "[DONE]":
        return None
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        if "test_complete" in clean and "success" in clean:
            return {"type": "test_complete", "success": '"success":true' in clean or "'success':true" in clean}
    return None
