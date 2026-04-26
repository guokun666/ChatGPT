#!/usr/bin/env python3
"""Migrate legacy codex-multi-proxy accounts into Codex Admin SQLite.

This script intentionally uses only Python stdlib so it can run on the host
before the Docker image is built. It never prints access_token/refresh_token/
id_token or the full generated API key.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = os.getenv("CODEX_ADMIN_DB", "/home/apple/codex-admin/codex-admin/data/codex-admin.sqlite3")
LEGACY_ACCOUNTS_FILE = os.getenv("LEGACY_ACCOUNTS_FILE", "/home/apple/codex-multi-proxy/data/accounts.json")
KEY_FILE = os.getenv("CODEX_PROXY_KEY_FILE", "/home/apple/codex-admin/codex-admin/data/model-family-codex-api-key.txt")
KEY_NAME = os.getenv("CODEX_PROXY_KEY_NAME", "model-family-codex")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def generate_api_key() -> str:
    return f"ck-{secrets.token_urlsafe(32)}"


def key_preview(key: str) -> str:
    return f"{key[:8]}...{key[-4:]}"


def codex_native_menu_models() -> list[dict[str, Any]]:
    efforts = ["low", "medium", "high", "xhigh"]
    return [
        {"id": "gpt-5.4", "label": "GPT-5.4", "reasoning_efforts": efforts},
        {"id": "gpt-5.2-codex", "label": "GPT-5.2-Codex", "reasoning_efforts": efforts},
        {"id": "gpt-5.1-codex-max", "label": "GPT-5.1-Codex-Max", "reasoning_efforts": efforts},
        {"id": "gpt-5.4-mini", "label": "GPT-5.4-Mini", "reasoning_efforts": efforts},
        {"id": "gpt-5.3-codex", "label": "GPT-5.3-Codex", "reasoning_efforts": efforts},
        {"id": "gpt-5.3-codex-spark", "label": "GPT-5.3-Codex-Spark", "reasoning_efforts": efforts},
        {"id": "gpt-5.2", "label": "GPT-5.2", "reasoning_efforts": efforts},
        {"id": "gpt-5.1-codex-mini", "label": "GPT-5.1-Codex-Mini", "reasoning_efforts": efforts},
    ]


def migrate_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT,
            device_id TEXT NOT NULL,
            auth_raw TEXT NOT NULL,
            access_token TEXT,
            refresh_token TEXT,
            expires_at TEXT,
            status TEXT NOT NULL DEFAULT 'normal',
            failure_count INTEGER NOT NULL DEFAULT 0,
            last_success_at TEXT,
            last_failure_at TEXT,
            status_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            deleted_reason TEXT,
            UNIQUE(device_id)
        );
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            key TEXT NOT NULL UNIQUE,
            key_preview TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            rate_limit_per_minute INTEGER,
            model_scopes TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_used_at TEXT
        );
        CREATE TABLE IF NOT EXISTS research_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            content TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(account_id) REFERENCES accounts(id)
        );
        """
    )


def extract_auth_fields(auth_json: dict[str, Any]) -> dict[str, Any]:
    tokens = auth_json.get("tokens") if isinstance(auth_json.get("tokens"), dict) else {}
    device_id = auth_json.get("device_id") or tokens.get("device_id") or tokens.get("deviceId")
    account_id = auth_json.get("account_id") or tokens.get("account_id") or tokens.get("sub")
    access_token = auth_json.get("access_token") or tokens.get("access_token") or tokens.get("accessToken")
    refresh_token = auth_json.get("refresh_token") or tokens.get("refresh_token") or tokens.get("refreshToken")
    id_token = auth_json.get("id_token") or tokens.get("id_token") or tokens.get("idToken")
    expires_at = auth_json.get("expires_at") or tokens.get("expires_at") or tokens.get("expire_at")
    status_reason = None
    if not account_id:
        account_id = device_id
    if not device_id and account_id:
        device_id = account_id
        status_reason = "auth.json has no device_id; account_id is being used as the stable device key"
    if not device_id:
        raise ValueError("auth_json missing device_id and account_id")
    if not access_token:
        raise ValueError("auth_json missing access_token")
    if not refresh_token:
        raise ValueError("auth_json missing refresh_token")
    if not id_token:
        raise ValueError("auth_json missing id_token")
    return {
        "account_id": account_id or device_id,
        "device_id": device_id,
        "auth_raw": json_dumps(auth_json),
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "status_reason": status_reason,
    }


def legacy_account_to_auth_json(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "auth_mode": item.get("auth_mode") or "chatgpt-oauth",
        "tokens": {
            "account_id": item.get("account_id") or item.get("email") or item.get("device_id"),
            "access_token": item.get("access_token"),
            "refresh_token": item.get("refresh_token"),
            "id_token": item.get("id_token"),
        },
        "meta": {**(item.get("meta") or {}), "source": "legacy-codex-multi-proxy"},
    }


def import_accounts(conn: sqlite3.Connection, accounts: list[dict[str, Any]]) -> int:
    imported = 0
    now = utc_now()
    for item in accounts:
        try:
            fields = extract_auth_fields(legacy_account_to_auth_json(item))
        except ValueError as exc:
            print(f"skip account {item.get('account_id') or item.get('email') or 'unknown'}: {exc}")
            continue
        conn.execute(
            """
            INSERT INTO accounts (
                account_id, device_id, auth_raw, access_token, refresh_token,
                expires_at, status, status_reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'normal', ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                account_id=excluded.account_id,
                auth_raw=excluded.auth_raw,
                access_token=excluded.access_token,
                refresh_token=excluded.refresh_token,
                expires_at=excluded.expires_at,
                status='normal',
                status_reason=excluded.status_reason,
                deleted_at=NULL,
                deleted_reason=NULL,
                updated_at=excluded.updated_at
            """,
            (
                fields["account_id"],
                fields["device_id"],
                fields["auth_raw"],
                fields["access_token"],
                fields["refresh_token"],
                fields["expires_at"],
                fields["status_reason"],
                now,
                now,
            ),
        )
        imported += 1
    return imported


def ensure_proxy_key(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT key, key_preview FROM api_keys WHERE name = ?", (KEY_NAME,)).fetchone()
    if row:
        Path(KEY_FILE).write_text(row["key"], encoding="utf-8")
        os.chmod(KEY_FILE, 0o600)
        return row["key_preview"]

    key = generate_api_key()
    preview = key_preview(key)
    scopes = [item["id"] for item in codex_native_menu_models()]
    now = utc_now()
    conn.execute(
        """
        INSERT INTO api_keys (name, key, key_preview, status, rate_limit_per_minute, model_scopes, created_at, updated_at)
        VALUES (?, ?, ?, 'active', ?, ?, ?, ?)
        """,
        (KEY_NAME, key, preview, 120, json_dumps(scopes), now, now),
    )
    Path(KEY_FILE).write_text(key, encoding="utf-8")
    os.chmod(KEY_FILE, 0o600)
    return preview


def main() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(Path(LEGACY_ACCOUNTS_FILE).read_text(encoding="utf-8"))
    accounts = payload.get("accounts", [])
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        migrate_schema(conn)
        imported = import_accounts(conn, accounts)
        preview = ensure_proxy_key(conn)
        conn.commit()
    print(json.dumps({"imported_accounts": imported, "api_key_preview": preview, "api_key_file": KEY_FILE}, ensure_ascii=False))


if __name__ == "__main__":
    main()
