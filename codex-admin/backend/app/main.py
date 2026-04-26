from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .schemas import (
    AccountUpdate,
    ApiKeyCreate,
    ApiKeyUpdate,
    ExceptionCreate,
    ImportAuthRequest,
    ResearchNoteCreate,
    UpdateAccountStatusRequest,
)
from .storage import (
    Database,
    account_summary,
    api_key_summary,
    extract_auth_fields,
    generate_api_key,
    key_preview,
    row_to_account,
    row_to_api_key,
    utc_now,
)


DEFAULT_DB_PATH = os.getenv(
    "CODEX_ADMIN_DB",
    str((Path(__file__).resolve().parents[1] / "data" / "codex-admin.sqlite3")),
)


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def create_app(db_path: str = DEFAULT_DB_PATH) -> FastAPI:
    db = Database(db_path)
    app = FastAPI(title="Codex Admin", version="0.1.0")
    app.state.db = db
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/accounts/import", status_code=201)
    def import_account(payload: ImportAuthRequest) -> dict[str, Any]:
        try:
            fields = extract_auth_fields(payload.auth_json)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        now = utc_now()
        try:
            with db.connect() as conn:
                cursor = conn.execute(
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
                        status_reason=excluded.status_reason,
                        updated_at=excluded.updated_at
                    RETURNING *
                    """,
                    (
                        fields["account_id"],
                        fields["device_id"],
                        fields["auth_raw"],
                        fields["access_token"],
                        fields["refresh_token"],
                        fields["expires_at"],
                        fields.get("status_reason"),
                        now,
                        now,
                    ),
                )
                row = cursor.fetchone()
        except sqlite3.Error as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return row_to_account(row)

    @app.get("/api/accounts")
    def list_accounts(include_deleted: bool = Query(False)) -> dict[str, Any]:
        with db.connect() as conn:
            if include_deleted:
                rows = conn.execute("SELECT * FROM accounts ORDER BY updated_at DESC, id DESC").fetchall()
            else:
                rows = conn.execute("SELECT * FROM accounts WHERE deleted_at IS NULL ORDER BY updated_at DESC, id DESC").fetchall()
        items = [row_to_account(row) for row in rows]
        return {"summary": account_summary(items), "items": items}

    @app.get("/api/accounts/{account_id}")
    def get_account(account_id: int) -> dict[str, Any]:
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="account not found")
        return row_to_account(row)

    @app.patch("/api/accounts/{account_id}")
    def update_account(account_id: int, payload: AccountUpdate) -> dict[str, Any]:
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return get_account(account_id)
        auth_updates: dict[str, Any] = {}
        if payload.auth_json is not None:
            try:
                auth_updates = extract_auth_fields(payload.auth_json)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        with db.connect() as conn:
            existing = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="account not found")
            try:
                row = conn.execute(
                    """
                    UPDATE accounts SET
                        account_id = COALESCE(?, account_id),
                        device_id = COALESCE(?, device_id),
                        auth_raw = COALESCE(?, auth_raw),
                        access_token = COALESCE(?, access_token),
                        refresh_token = COALESCE(?, refresh_token),
                        expires_at = COALESCE(?, expires_at),
                        status = COALESCE(?, status),
                        status_reason = ?,
                        updated_at = ?
                    WHERE id = ?
                    RETURNING *
                    """,
                    (
                        auth_updates.get("account_id") or updates.get("account_id"),
                        auth_updates.get("device_id") or updates.get("device_id"),
                        auth_updates.get("auth_raw"),
                        auth_updates.get("access_token"),
                        auth_updates.get("refresh_token"),
                        auth_updates.get("expires_at") or updates.get("expires_at"),
                        updates.get("status"),
                        auth_updates.get("status_reason") if payload.auth_json is not None else updates.get("status_reason", existing["status_reason"]),
                        utc_now(),
                        account_id,
                    ),
                ).fetchone()
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail="device_id already exists") from exc
        return row_to_account(row)

    @app.delete("/api/accounts/{account_id}", status_code=204)
    def delete_account(account_id: int) -> None:
        now = utc_now()
        with db.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE accounts SET deleted_at = ?, deleted_reason = ?, updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (now, "manual delete", now, account_id),
            )
            if cursor.rowcount == 0:
                row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="account not found")
        return None

    @app.post("/api/accounts/{account_id}/restore")
    def restore_account(account_id: int) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="account not found")
            restored = conn.execute(
                """
                UPDATE accounts SET deleted_at = NULL, deleted_reason = NULL, updated_at = ?
                WHERE id = ?
                RETURNING *
                """,
                (now, account_id),
            ).fetchone()
        return row_to_account(restored)

    @app.patch("/api/accounts/{account_id}/status")
    def update_account_status(account_id: int, payload: UpdateAccountStatusRequest) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="account not found")
            failure_count = row["failure_count"] + (1 if payload.status in {"limited", "banned", "expired"} else 0)
            cursor = conn.execute(
                """
                UPDATE accounts SET
                    status = ?,
                    status_reason = ?,
                    failure_count = ?,
                    last_failure_at = CASE WHEN ? IN ('limited', 'banned', 'expired') THEN ? ELSE last_failure_at END,
                    updated_at = ?
                WHERE id = ?
                RETURNING *
                """,
                (payload.status, payload.reason, failure_count, payload.status, now, now, account_id),
            )
            updated = cursor.fetchone()
        return row_to_account(updated)

    @app.post("/api/research-notes", status_code=201)
    def create_research_note(payload: ResearchNoteCreate) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO research_notes (title, status, content, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                RETURNING *
                """,
                (payload.title, payload.status, payload.content, now, now),
            ).fetchone()
        return dict(row)

    @app.get("/api/research-notes")
    def list_research_notes() -> dict[str, Any]:
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM research_notes ORDER BY updated_at DESC, id DESC").fetchall()
        return {"items": [dict(row) for row in rows]}

    @app.post("/api/exceptions", status_code=201)
    def create_exception(payload: ExceptionCreate) -> dict[str, Any]:
        now = utc_now()
        with db.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO exceptions (account_id, level, message, detail, created_at)
                VALUES (?, ?, ?, ?, ?)
                RETURNING *
                """,
                (payload.account_id, payload.level, payload.message, payload.detail, now),
            ).fetchone()
        return dict(row)

    @app.get("/api/exceptions")
    def list_exceptions() -> dict[str, Any]:
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT exceptions.*, accounts.device_id
                FROM exceptions
                LEFT JOIN accounts ON accounts.id = exceptions.account_id
                ORDER BY exceptions.created_at DESC, exceptions.id DESC
                """,
            ).fetchall()
        return {"items": [dict(row) for row in rows]}

    @app.post("/api/api-keys", status_code=201)
    def create_api_key(payload: ApiKeyCreate) -> dict[str, Any]:
        now = utc_now()
        key = generate_api_key()
        with db.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO api_keys (name, key, key_preview, status, rate_limit_per_minute, model_scopes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING *
                """,
                (
                    payload.name,
                    key,
                    key_preview(key),
                    payload.status,
                    payload.rate_limit_per_minute,
                    json_dumps(payload.model_scopes),
                    now,
                    now,
                ),
            ).fetchone()
        return row_to_api_key(row, include_key=True)

    @app.get("/api/api-keys")
    def list_api_keys() -> dict[str, Any]:
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM api_keys ORDER BY updated_at DESC, id DESC").fetchall()
        items = [row_to_api_key(row) for row in rows]
        return {"summary": api_key_summary(items), "items": items}

    @app.patch("/api/api-keys/{api_key_id}")
    def update_api_key(api_key_id: int, payload: ApiKeyUpdate) -> dict[str, Any]:
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (api_key_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="api key not found")
            updated = {
                "name": payload.name if payload.name is not None else row["name"],
                "status": payload.status if payload.status is not None else row["status"],
                "rate_limit_per_minute": payload.rate_limit_per_minute if payload.rate_limit_per_minute is not None else row["rate_limit_per_minute"],
                "model_scopes": json_dumps(payload.model_scopes) if payload.model_scopes is not None else row["model_scopes"],
            }
            cursor = conn.execute(
                """
                UPDATE api_keys SET name = ?, status = ?, rate_limit_per_minute = ?, model_scopes = ?, updated_at = ?
                WHERE id = ?
                RETURNING *
                """,
                (updated["name"], updated["status"], updated["rate_limit_per_minute"], updated["model_scopes"], utc_now(), api_key_id),
            )
            updated_row = cursor.fetchone()
        return row_to_api_key(updated_row)

    @app.delete("/api/api-keys/{api_key_id}", status_code=204)
    def delete_api_key(api_key_id: int) -> None:
        with db.connect() as conn:
            cursor = conn.execute("DELETE FROM api_keys WHERE id = ?", (api_key_id,))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="api key not found")
        return None

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        accounts = list_accounts()["summary"]
        notes = list_research_notes()["items"]
        exceptions = list_exceptions()["items"]
        note_summary = {"total": len(notes), "done": 0, "pending": 0, "blocked": 0}
        for note in notes:
            note_summary[note["status"]] += 1
        exception_summary = {"total": len(exceptions), "info": 0, "warning": 0, "error": 0}
        for item in exceptions:
            exception_summary[item["level"]] += 1
        api_keys = list_api_keys()["items"]
        return {
            "accounts": accounts,
            "research_notes": note_summary,
            "exceptions": exception_summary,
            "api_keys": api_key_summary(api_keys),
        }

    return app


app = create_app()
