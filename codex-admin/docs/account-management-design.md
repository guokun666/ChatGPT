# Codex Admin Account Management Design

## Context

The account table currently supports import and status switching, but it does not support editing account metadata or deleting/removing rows from the visible account pool. Imported accounts can therefore accumulate bad fallback metadata and cannot be cleaned up from the UI.

## Skill audit

Existing useful skills found:

- `standalone-admin-console-fastapi-react-sqlite`: current project pattern for isolated FastAPI + React + SQLite admin console.
- `popular-web-designs` + `linear.app` template: visual design guidance for a dark technical admin UI.
- `test-driven-development`: required implementation discipline.
- `writing-plans`: design-before-implementation structure.
- `requesting-code-review`: pre-commit verification guidance.

Skills added after research:

- `admin-crud-ui-ux`: CRUD table, edit/delete flow, confirmation, feedback, accessibility.
- `fastapi-sqlite-crud-best-practices`: FastAPI + SQLite CRUD API and migration-ready backend guidance.
- `sensitive-admin-console-design`: credential/admin-console design, auditability, least privilege, secret handling, destructive action safety.

## Product goals

1. Accounts imported into the account library can be edited from the UI.
2. Accounts can be deleted from the active visible pool.
3. Delete should be safe and auditable for a credential-management admin page.
4. Secret fields must remain hidden in normal API responses.
5. The implementation should stay SQLite-first but not block future MySQL/PostgreSQL migration.

## Backend design

### Data lifecycle

Use soft delete, not hard delete, for accounts.

Rationale:

- Accounts contain credential metadata and may be referenced by exceptions or future audit logs.
- Deleting should remove the account from the active pool/list while retaining forensic context.
- A future restore flow remains possible.

Add columns to `accounts`:

```text
deleted_at TEXT NULL
deleted_reason TEXT NULL
```

Default list behavior excludes deleted records:

```text
GET /api/accounts -> active/non-deleted records only
```

Optional inspection:

```text
GET /api/accounts?include_deleted=true
```

### API endpoints

Add:

```text
GET    /api/accounts/{id}
PATCH  /api/accounts/{id}
DELETE /api/accounts/{id}
POST   /api/accounts/{id}/restore
```

Keep existing:

```text
PATCH /api/accounts/{id}/status
```

### Editable fields

Allow editing only safe metadata:

```text
account_id
device_id
expires_at
status
status_reason
```

Do not expose/edit through this form:

```text
auth_raw
access_token
refresh_token
```

To update credentials, re-import auth.json.

### Delete semantics

`DELETE /api/accounts/{id}`:

- Sets `deleted_at` to current UTC time.
- Sets `deleted_reason`, default `manual delete`.
- Returns `204 No Content`.
- Subsequent default `GET /api/accounts` no longer shows it.

`POST /api/accounts/{id}/restore`:

- Clears `deleted_at` / `deleted_reason`.
- Returns restored account metadata.

### Response safety

`row_to_account()` must never return:

```text
auth_raw
access_token
refresh_token
```

It may return safe lifecycle metadata:

```text
deleted_at
deleted_reason
```

## Frontend design

### Account table actions

Replace the current many-status-button row with clearer actions:

```text
编辑 | 状态下拉 | 删除
```

Reason:

- Current row expands into many wrapped buttons, which is visually noisy.
- Users expect visible Edit/Delete actions in CRUD tables.
- Status is a field, not five separate primary row actions.

### Edit flow

Use a compact modal/drawer-style dialog:

Fields:

- Account ID
- DeviceID
- Expires At
- Status select
- Reason / note

Actions:

- 保存
- 取消

Behavior:

- Preserve entered values on validation error.
- Disable save while request is pending.
- Show success/failure message.
- Refresh table after save.

### Delete flow

Use a confirmation dialog:

Title:

```text
删除账号？
```

Body includes the concrete target:

```text
这会把账号 {account_id || device_id} 从默认账号库中移除。记录会软删除，后续可在后端恢复。
```

Actions:

- 取消
- 删除账号

Behavior:

- Destructive button is styled as danger.
- Delete removes the row from the default table after success.
- Show success/failure message.

### Accessibility

- Use real buttons, labels, inputs, selects, and semantic tables.
- Modal uses `role="dialog"`, `aria-modal="true"`, and title association.
- Async messages use visible message region.
- Status badges include text, not only color.

## Acceptance criteria

Backend:

- `PATCH /api/accounts/{id}` edits safe metadata.
- `DELETE /api/accounts/{id}` soft-deletes and hides from default list.
- `GET /api/accounts?include_deleted=true` includes soft-deleted rows.
- `POST /api/accounts/{id}/restore` restores row.
- Secret fields are never returned.
- Tests pass.

Frontend:

- Account rows show visible 编辑 and 删除 controls.
- Edit modal can change account metadata/status/reason.
- Delete confirmation removes row from default list.
- Existing import/API-key/research/exception features still work.
- Vite build passes.
