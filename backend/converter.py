import json
from datetime import datetime, timezone
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sub2api_document(accounts: list[dict]) -> dict:
    return {
        "exported_at": iso_now(),
        "proxies": [],
        "accounts": accounts,
    }


def _credentials(account: dict) -> dict:
    creds = account.get("credentials")
    return creds if isinstance(creds, dict) else {}


def _extra(account: dict) -> dict:
    extra = account.get("extra")
    return extra if isinstance(extra, dict) else {}


def first_non_empty(*values):
    for value in values:
        if value not in (None, ""):
            return value
    return None


def account_to_cpa(account: dict) -> dict:
    creds = _credentials(account)
    extra = _extra(account)
    account_id = first_non_empty(
        creds.get("account_id"),
        creds.get("chatgpt_account_id"),
        extra.get("chatgpt_account_id"),
        account.get("account_id"),
        account.get("id"),
        account.get("name"),
    )
    email = first_non_empty(creds.get("email"), extra.get("email"), account.get("email"), account.get("name"))
    plan_type = first_non_empty(creds.get("plan_type"), extra.get("plan_type"), account.get("plan_type"))
    cpa = {
        "type": "codex",
        "account_id": account_id,
        "chatgpt_account_id": account_id,
        "email": email,
        "name": account.get("name") or email or account_id,
        "plan_type": plan_type,
        "chatgpt_plan_type": plan_type,
        "id_token": first_non_empty(creds.get("id_token"), account.get("id_token")),
        "access_token": first_non_empty(creds.get("access_token"), account.get("access_token")),
        "refresh_token": first_non_empty(creds.get("refresh_token"), account.get("refresh_token"), ""),
        "session_token": first_non_empty(creds.get("session_token"), account.get("session_token"), ""),
        "expires_at": first_non_empty(creds.get("expires_at"), account.get("expires_at")),
        "providerSpecificData": {
            "chatgptAccountId": account_id,
            "chatgptPlanType": plan_type,
        },
        "provider": "codex",
        "authType": "oauth",
        "isActive": True,
    }
    return {key: value for key, value in cpa.items() if value is not None}


def cpa_document(accounts: list[dict]) -> list[dict]:
    return [account_to_cpa(account) for account in accounts]


def build_accounts_zip(card_code: str, accounts: list[dict]) -> bytes:
    sub2api_json = json.dumps(sub2api_document(accounts), ensure_ascii=False, indent=2)
    cpa_json = json.dumps(cpa_document(accounts), ensure_ascii=False, indent=2)
    out = BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as zf:
        zf.writestr("sub2api.json", sub2api_json)
        zf.writestr("cpa.json", cpa_json)
    return out.getvalue()


def safe_zip_name(card_code: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in card_code)
    return f"accounts-{safe}.zip"

