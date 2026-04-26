from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .schemas import ExceptionCreate, ImportAuthRequest, ResearchNoteCreate, UpdateAccountStatusRequest
from .storage import Database, account_summary, extract_auth_fields, row_to_account, utc_now


DEFAULT_DB_PATH = os.getenv(
    "CODEX_ADMIN_DB",
    str((Path(__file__).resolve().parents[1] / "data" / "codex-admin.sqlite3")),
)


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
                        expires_at, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'normal', ?, ?)
                    ON CONFLICT(device_id) DO UPDATE SET
                        account_id=excluded.account_id,
                        auth_raw=excluded.auth_raw,
                        access_token=excluded.access_token,
                        refresh_token=excluded.refresh_token,
                        expires_at=excluded.expires_at,
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
                        now,
                        now,
                    ),
                )
                row = cursor.fetchone()
        except sqlite3.Error as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return row_to_account(row)

    @app.get("/api/accounts")
    def list_accounts() -> dict[str, Any]:
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM accounts ORDER BY updated_at DESC, id DESC").fetchall()
        items = [row_to_account(row) for row in rows]
        return {"summary": account_summary(items), "items": items}

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
        return {"accounts": accounts, "research_notes": note_summary, "exceptions": exception_summary}

    return app


app = create_app()
