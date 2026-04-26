# Codex Admin

A standalone admin console for managing a Codex `auth.json` account pool, research notes, and abnormal events.

The implementation is intentionally isolated under `codex-admin/` so it can evolve without polluting the core SDK package.

## Current stack

- Backend: Python + FastAPI
- Storage: SQLite by default
- Frontend: React + Vite

The backend uses a small storage layer so SQLite can later be replaced by MySQL or PostgreSQL with limited surface-area changes.

## Features

- Import or update a single native `auth.json` by pasting JSON into the admin page.
- Store account metadata and raw auth JSON in SQLite.
- Never expose `access_token`, `refresh_token`, or `auth_raw` through list/detail API responses.
- Account status management:
  - `normal`
  - `limited`
  - `banned`
  - `expired`
  - `disabled`
- Dashboard summaries for accounts, research notes, and exceptions.
- Research note tracking for reverse-engineering/validation progress.
- Exception tracking for quota, auth, timeout, and risk-control events.

## Backend quick start

```bash
cd codex-admin/backend
python3 -m pip install -r requirements.txt
CODEX_ADMIN_DB=./data/codex-admin.sqlite3 uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/api/health
```

Run backend tests:

```bash
cd <repo-root>
PYTHONPATH=codex-admin/backend python3 -m pytest codex-admin/backend/tests/test_api.py -q
```

## Frontend quick start

```bash
cd codex-admin/frontend
npm install
VITE_API_BASE=http://localhost:8000 npm run dev
```

Open:

```text
http://localhost:5173
```

Build frontend:

```bash
cd codex-admin/frontend
npm run build
```

## API overview

```text
GET  /api/health
GET  /api/dashboard
POST /api/accounts/import
GET  /api/accounts
PATCH /api/accounts/{id}/status
POST /api/research-notes
GET  /api/research-notes
POST /api/exceptions
GET  /api/exceptions
```

## Database notes

SQLite file defaults to:

```text
./data/codex-admin.sqlite3
```

Override with:

```bash
CODEX_ADMIN_DB=/private/path/codex-admin.sqlite3
```

For future MySQL/PostgreSQL support, keep callers behind the existing storage/repository boundary rather than writing SQL directly from route handlers.

## Security notes before production use

This first version is a local/internal admin implementation. Before exposing it on a network, add:

- Login/session authentication.
- CSRF protection or same-site cookie strategy if browser-authenticated.
- Encryption-at-rest for `auth_raw`, `access_token`, and `refresh_token`.
- Audit logs for import/status changes.
- API key or mTLS in front of the backend.
