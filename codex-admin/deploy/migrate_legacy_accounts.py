#!/usr/bin/env python3
"""Migrate legacy codex-multi-proxy accounts into Codex Admin SQLite.

Run on the Google server from the repository root:

  PYTHONPATH=codex-admin/backend \
  CODEX_ADMIN_DB=/home/apple/codex-admin/codex-admin/data/codex-admin.sqlite3 \
  LEGACY_ACCOUNTS_FILE=/home/apple/codex-multi-proxy/data/accounts.json \
  python3 codex-admin/deploy/migrate_legacy_accounts.py

This script never prints access_token/refresh_token/id_token or the full generated API key.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from app.main import codex_native_menu_models, json_dumps
from app.storage import Database, extract_auth_fields, generate_api_key, key_preview, utc_now

DB_PATH = os.getenv("CODEX_ADMIN_DB", "/home/apple/codex-admin/codex-admin/data/codex-admin.sqlite3")
LEGACY_ACCOUNTS_FILE = os.getenv("LEGACY_ACCOUNTS_FILE", "/home/apple/codex-multi-proxy/data/accounts.json")
KEY_FILE = os.getenv("CODEX_PROXY_KEY_FILE", "/home/apple/codex-admin/codex-admin/data/model-family-codex-api-key.txt")
KEY_NAME = os.getenv("CODEX_PROXY_KEY_NAME", "model-family-codex")


def legacy_account_to_auth_json(item: dict) -> dict:
    # Preserve native-like token shape so refresh and future validation can use the same parser.
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


def import_accounts(conn: sqlite3.Connection, accounts: list[dict]) -> int:
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
    Database(DB_PATH)
    payload = json.loads(Path(LEGACY_ACCOUNTS_FILE).read_text(encoding="utf-8"))
    accounts = payload.get("accounts", [])
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        imported = import_accounts(conn, accounts)
        preview = ensure_proxy_key(conn)
        conn.commit()
    print(json.dumps({"imported_accounts": imported, "api_key_preview": preview, "api_key_file": KEY_FILE}, ensure_ascii=False))


if __name__ == "__main__":
    main()
