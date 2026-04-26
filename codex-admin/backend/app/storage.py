from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def migrate(self) -> None:
        with self.connect() as conn:
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
                """,
            )
            self._ensure_column(conn, "accounts", "deleted_at", "TEXT")
            self._ensure_column(conn, "accounts", "deleted_reason", "TEXT")

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def row_to_account(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "account_id": row["account_id"],
        "device_id": row["device_id"],
        "expires_at": row["expires_at"],
        "status": row["status"],
        "failure_count": row["failure_count"],
        "last_success_at": row["last_success_at"],
        "last_failure_at": row["last_failure_at"],
        "status_reason": row["status_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "deleted_at": row["deleted_at"],
        "deleted_reason": row["deleted_reason"],
    }


def extract_auth_fields(auth_json: dict[str, Any]) -> dict[str, Any]:
    tokens = auth_json.get("tokens") if isinstance(auth_json.get("tokens"), dict) else {}
    device_id = (
        auth_json.get("device_id")
        or auth_json.get("deviceId")
        or auth_json.get("deviceID")
        or tokens.get("device_id")
        or tokens.get("deviceId")
        or tokens.get("deviceID")
    )
    account_id = (
        auth_json.get("account_id")
        or auth_json.get("user_id")
        or auth_json.get("sub")
        or tokens.get("account_id")
        or tokens.get("user_id")
        or tokens.get("sub")
    )
    access_token = auth_json.get("access_token") or auth_json.get("accessToken") or tokens.get("access_token") or tokens.get("accessToken")
    refresh_token = auth_json.get("refresh_token") or auth_json.get("refreshToken") or tokens.get("refresh_token") or tokens.get("refreshToken")
    id_token = auth_json.get("id_token") or auth_json.get("idToken") or tokens.get("id_token") or tokens.get("idToken")
    expires_at = auth_json.get("expires_at") or auth_json.get("expire_at") or auth_json.get("expiresAt") or tokens.get("expires_at") or tokens.get("expire_at") or tokens.get("expiresAt")
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
        "auth_raw": json.dumps(auth_json, ensure_ascii=False),
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "status_reason": status_reason,
    }


def account_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(items), "normal": 0, "limited": 0, "banned": 0, "expired": 0, "disabled": 0}
    for item in items:
        if item["status"] in summary:
            summary[item["status"]] += 1
    return summary


def generate_api_key() -> str:
    return f"ck-{secrets.token_urlsafe(32)}"


def key_preview(key: str) -> str:
    return f"{key[:8]}...{key[-4:]}"


def row_to_api_key(row: sqlite3.Row, include_key: bool = False) -> dict[str, Any]:
    data = {
        "id": row["id"],
        "name": row["name"],
        "key_preview": row["key_preview"],
        "status": row["status"],
        "rate_limit_per_minute": row["rate_limit_per_minute"],
        "model_scopes": json.loads(row["model_scopes"] or "[]"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_used_at": row["last_used_at"],
    }
    if include_key:
        data["key"] = row["key"]
    return data


def api_key_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(items), "active": 0, "disabled": 0}
    for item in items:
        if item["status"] in summary:
            summary[item["status"]] += 1
    return summary
