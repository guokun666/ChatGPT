from __future__ import annotations

import json
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
                """,
            )


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
    }


def extract_auth_fields(auth_json: dict[str, Any]) -> dict[str, Any]:
    device_id = auth_json.get("device_id") or auth_json.get("deviceId") or auth_json.get("deviceID")
    if not device_id:
        raise ValueError("auth_json missing device_id")
    return {
        "account_id": auth_json.get("account_id") or auth_json.get("user_id") or auth_json.get("sub") or device_id,
        "device_id": device_id,
        "auth_raw": json.dumps(auth_json, ensure_ascii=False),
        "access_token": auth_json.get("access_token") or auth_json.get("accessToken"),
        "refresh_token": auth_json.get("refresh_token") or auth_json.get("refreshToken"),
        "expires_at": auth_json.get("expires_at") or auth_json.get("expire_at") or auth_json.get("expiresAt"),
    }


def account_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(items), "normal": 0, "limited": 0, "banned": 0, "expired": 0, "disabled": 0}
    for item in items:
        if item["status"] in summary:
            summary[item["status"]] += 1
    return summary
