# Hermes Codex Native Gateway Design

This document records the implementation constraints and target architecture for a Hermes-integrated OpenAI-compatible gateway backed by the native OpenAI Codex Desktop/CLI protocol.

## 1. Hard constraints

- Reverse target: OpenAI Codex Desktop / CLI native protocol only.
- Explicitly excluded: web protocol, browser cookies, and browser traffic replay.
- Credential carrier: batch import of native `auth.json` files.
- Account routing: never use simple round-robin, random account switching, or weighted random spreading for healthy traffic.
- Cache requirement: preserve OpenAI account-level cache locality.
- Public interface: expose a standard OpenAI-compatible BaseURL plus a custom API key.
- Required operations: automatic token refresh, circuit breaking for abnormal accounts, and Codex-only model support.

## 2. Technology decision

### Native reverse-engineering kernel

Use the core SDK from `acheong08/ChatGPT` as the lower-level native protocol implementation basis because it contains the complete Codex CLI private authentication path, device ID chain, native `auth.json` parsing, and refresh token handling.

### Gateway and scheduling layer

Implement the gateway and load layer inside Hermes with sticky-session consistent-hash scheduling.

Do not depend on third-party lightweight proxy projects as the primary runtime layer. The goal is a small Hermes-native integration with explicit account lifecycle control, cache-preserving routing, and OpenAI-compatible API exposure.

## 3. Cache preservation model

Codex cache isolation is effectively keyed by:

```text
OpenAI account ID + DeviceID + model + input context
```

Cache locality is destroyed when requests are randomly assigned to different `auth.json` files, because both account ID and DeviceID change. Therefore, normal traffic must bind one downstream caller identity to one account credential and stay there until passive failover is necessary.

## 4. Account pool data model

```text
CodexAccountPool
├─ accounts[]
│  ├─ auth_raw: complete auth.json raw text
│  ├─ account_id: OpenAI account/user identifier, when available
│  ├─ device_id: DeviceID extracted from auth.json or native auth metadata
│  ├─ access_token
│  ├─ refresh_token
│  ├─ expire_at
│  ├─ status: normal / limited / banned / expired
│  ├─ failure_count
│  ├─ last_success_at
│  ├─ last_failure_at
│  └─ circuit_open_until
```

Implementation notes:

- Store the raw `auth.json` only in a private credential store or encrypted local store.
- Never mix DeviceID or conversation/session state between accounts.
- Keep per-account runtime metadata outside the raw auth file so account state can be rebuilt and audited.

## 5. Scheduling rule

Mandatory algorithm: consistent hashing with sticky session semantics.

Hash input priority:

1. `X-Session-Id`, when supplied by the downstream client.
2. Custom downstream API key identity, derived from `Authorization: Bearer ...`.
3. Composite fingerprint: client IP + User-Agent.

Forbidden strategies:

- Random routing.
- Sequential round-robin.
- Weighted random spreading for normal healthy traffic.

Healthy traffic policy:

```text
downstream caller identity -> consistent hash ring -> fixed Codex account
```

The gateway must not proactively rotate accounts for normal requests.

## 6. Passive failover triggers

Account switching is allowed only when the bound account is unavailable or unsafe to use:

- `access_token` expired and refresh failed.
- Upstream returns 429 rate limit / quota limited.
- Upstream returns 401 authentication failure.
- Consecutive request timeout or connection failure crosses threshold.
- Account is explicitly marked as risk-controlled or banned.

Circuit breaker behavior:

```text
normal -> limited/expired/banned -> temporarily removed from hash ring -> periodic recovery probe -> normal
```

The replacement account should be selected by re-hashing over the active healthy account set, not by random fallback.

## 7. External API contract

BaseURL:

```text
https://hermes-domain.com/codex/v1
```

Authentication:

```text
Authorization: Bearer {custom-global-api-key}
```

Compatible endpoints:

```text
POST /v1/chat/completions
POST /v1/completions
GET  /v1/models
```

Supported Codex-only model aliases:

```text
gpt-4o-codex
codex-code
code-mini
gpt-4-codex
```

Streaming and non-streaming responses must be OpenAI-compatible. Streaming output uses SSE and emits OpenAI-style delta chunks.

## 8. Credential import and maintenance

Credential import modes:

- Batch upload of multiple `auth.json` files.
- Directory traversal import from a private local path.

Maintenance jobs:

- Refresh access tokens before expiry using the native refresh path.
- Quarantine expired, risk-controlled, or broken credentials.
- Keep per-account DeviceID and session context isolated.
- Rate-limit each account independently to reduce risk-control triggers.

## 9. Risk-control principles

- Use only CLI/Desktop native protocol semantics.
- Do not attach web fingerprint material or browser cookies.
- Reuse a stable DeviceID for each account over the long term.
- Apply per-account concurrency and request-rate limits.
- Remove abnormal accounts from the active ring quickly so they do not poison the full pool.

## 10. Rejected alternatives

### router-for-me/CLIProxyAPI

Rejected because it uses simple polling/round-robin behavior, has no sticky session guarantee, and destroys cache hit rate across accounts.

### Lightweight Codex proxy variants

Rejected because most implementations have incomplete multi-account behavior, weak circuit breaking, and incomplete automatic refresh handling.

### Pandora mixed protocol approaches

Rejected because they mix web-side protocol behavior with native Codex access, which weakens native Codex support and increases risk-control exposure.

## 11. Initial development milestones

1. Add native `auth.json` loader and validation.
2. Implement `CodexAccountPool` with account status and refresh lifecycle.
3. Implement consistent-hash sticky scheduler.
4. Add OpenAI-compatible `/v1/models`, `/v1/chat/completions`, and `/v1/completions` gateway routes.
5. Add SSE streaming adapter.
6. Add per-account rate limiting and circuit breaker.
7. Add integration tests for sticky routing, failover, token refresh, and model alias mapping.
