from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from .storage import Database, extract_auth_fields, utc_now

UPSTREAM_BASE_URL = "https://chatgpt.com"
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_OAUTH_REDIRECT_URI = "http://localhost:1455/auth/callback"


@dataclass(slots=True)
class ProxyResult:
    status_code: int
    body: bytes
    headers: dict[str, str]


UpstreamSender = Callable[[httpx.Request], httpx.Response]


def extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return None
    return authorization[len(prefix) :].strip()


def public_model_payload(models: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    return {"object": "list", "data": [{"id": item["id"], "object": "model"} for item in models]}


class CodexProxyService:
    def __init__(
        self,
        db: Database,
        *,
        upstream_base_url: str = UPSTREAM_BASE_URL,
        upstream_sender: UpstreamSender | None = None,
        cooldown_seconds: int = 300,
    ) -> None:
        self.db = db
        self.upstream_base_url = upstream_base_url.rstrip("/")
        self.cooldown_seconds = cooldown_seconds
        self._client = httpx.Client(timeout=120) if upstream_sender is None else None
        self._send = upstream_sender or self._client.send  # type: ignore[union-attr]

    def authenticate_api_key(self, authorization: str | None) -> dict[str, Any]:
        token = extract_bearer(authorization)
        if not token:
            raise HTTPException(status_code=401, detail="missing bearer api key")
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM api_keys WHERE key = ?", (token,)).fetchone()
            if not row:
                raise HTTPException(status_code=401, detail="invalid api key")
            if row["status"] != "active":
                raise HTTPException(status_code=403, detail=f"api key is not active: {row['status']}")
            return dict(row)

    def enforce_model_scope(self, api_key_row: dict[str, Any], model: str) -> None:
        scopes = json.loads(api_key_row.get("model_scopes") or "[]")
        if scopes and model not in scopes:
            raise HTTPException(status_code=403, detail=f"model {model} is not allowed by this api key")

    def proxy(self, path: str, body: bytes, incoming_headers: dict[str, str], api_key_row: dict[str, Any]) -> ProxyResult:
        request_spec = self._prepare_request(path, body)
        payload_model = request_spec.get("model")
        if isinstance(payload_model, str) and payload_model:
            self.enforce_model_scope(api_key_row, payload_model)

        attempts = 0
        last_response: httpx.Response | None = None
        tried_ids: set[int] = set()
        while True:
            account = self._choose_account(incoming_headers, api_key_row, tried_ids)
            tried_ids.add(int(account["id"]))
            response = self._send_upstream(account, incoming_headers, request_spec)
            last_response = response

            if response.status_code in {401, 403} and account.get("refresh_token"):
                try:
                    account = self._refresh_account(account)
                    response = self._send_upstream(account, incoming_headers, request_spec)
                    last_response = response
                except Exception:
                    self._mark_account_failure(account, "expired")
                    response = last_response

            if response.status_code < 500 and response.status_code != 429:
                self._mark_account_success(account)
                self._touch_api_key(api_key_row)
                return request_spec["adapt"](response)

            reason = "429" if response.status_code == 429 else str(response.status_code)
            self._mark_account_failure(account, reason)
            attempts += 1
            if attempts >= max(1, self._normal_account_count()) or len(tried_ids) >= self._normal_account_count():
                break

        if last_response is None:
            raise HTTPException(status_code=503, detail="no normal auth account available")
        return request_spec["adapt"](last_response)

    def _send_upstream(self, account: dict[str, Any], incoming_headers: dict[str, str], request_spec: dict[str, Any]) -> httpx.Response:
        request = httpx.Request(
            method="POST",
            url=self.upstream_base_url + request_spec["mapped_path"],
            content=request_spec["body"],
            headers=self._build_headers(account, incoming_headers, request_spec["accept"]),
        )
        return self._send(request)

    def _normal_account_count(self) -> int:
        with self.db.connect() as conn:
            row = conn.execute("SELECT count(*) AS n FROM accounts WHERE deleted_at IS NULL AND status = 'normal'").fetchone()
            return int(row["n"] or 0)

    def _choose_account(self, headers: dict[str, str], api_key_row: dict[str, Any], tried_ids: set[int]) -> dict[str, Any]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM accounts WHERE deleted_at IS NULL AND status = 'normal' ORDER BY id ASC"
            ).fetchall()
        accounts = [dict(row) for row in rows if int(row["id"]) not in tried_ids]
        if not accounts:
            raise HTTPException(status_code=503, detail="no normal auth account available")
        identity = self._routing_identity(headers, api_key_row)
        return max(accounts, key=lambda row: self._hash_score(f"{identity}:{row['account_id']}:{row['device_id']}"))

    @staticmethod
    def _routing_identity(headers: dict[str, str], api_key_row: dict[str, Any]) -> str:
        lowered = {k.lower(): v for k, v in headers.items()}
        for key in ("x-session-id", "x-conversation-id", "x-sticky-key"):
            if lowered.get(key):
                return f"header:{key}:{lowered[key]}"
        return f"api-key:{api_key_row['key']}"

    @staticmethod
    def _hash_score(value: str) -> int:
        return int(hashlib.sha256(value.encode("utf-8")).hexdigest(), 16)

    def _prepare_request(self, path: str, body: bytes) -> dict[str, Any]:
        if path in {"/v1/responses", "/v1/responses/compact"}:
            payload = json.loads(body.decode("utf-8")) if body else {}
            stream = bool(payload.get("stream"))
            mapped_path = "/backend-api/codex/responses/compact" if path.endswith("/compact") else "/backend-api/codex/responses"
            return {
                "mapped_path": mapped_path,
                "body": body,
                "model": payload.get("model"),
                "accept": "text/event-stream" if stream else "application/json",
                "adapt": lambda response: ProxyResult(response.status_code, response.content, self._response_headers(response.headers)),
            }

        if path == "/v1/chat/completions":
            payload = json.loads(body.decode("utf-8")) if body else {}
            stream = bool(payload.get("stream"))
            translated = self._chat_to_responses_payload(payload)
            return {
                "mapped_path": "/backend-api/codex/responses",
                "body": json.dumps(translated, ensure_ascii=False).encode("utf-8"),
                "model": payload.get("model"),
                "accept": "text/event-stream",
                "adapt": lambda response: self._adapt_chat_completions_response(response, payload, stream=stream),
            }
        raise HTTPException(status_code=404, detail="unsupported path")

    def _build_headers(self, account: dict[str, Any], incoming_headers: dict[str, str], accept: str) -> dict[str, str]:
        headers = {
            k.lower(): v
            for k, v in incoming_headers.items()
            if k.lower() not in {"host", "content-length", "authorization", "accept"}
        }
        headers["authorization"] = f"Bearer {account['access_token']}"
        headers["chatgpt-account-id"] = account["account_id"] or account["device_id"]
        headers.setdefault("openai-beta", "responses=experimental")
        headers.setdefault("originator", "codex_cli_rs")
        headers["content-type"] = "application/json"
        headers["accept"] = accept
        return headers

    def _chat_to_responses_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        messages = payload.get("messages") or []
        instructions_parts: list[str] = []
        input_items: list[dict[str, Any]] = []
        for raw_message in messages:
            if not isinstance(raw_message, dict):
                continue
            role = str(raw_message.get("role") or "user")
            text = self._coerce_message_text(raw_message.get("content"))
            if not text:
                continue
            if role in {"system", "developer"}:
                instructions_parts.append(text)
                continue
            content_type = "output_text" if role == "assistant" else "input_text"
            input_items.append({"role": role, "content": [{"type": content_type, "text": text}]})
        if not input_items:
            input_items = [{"role": "user", "content": [{"type": "input_text", "text": ""}]}]
        translated: dict[str, Any] = {
            "model": payload.get("model"),
            "instructions": "\n\n".join(instructions_parts) or "You are a helpful assistant.",
            "input": input_items,
            "store": False,
            "stream": True,
        }
        if isinstance(payload.get("previous_response_id"), str) and payload.get("previous_response_id"):
            translated["previous_response_id"] = payload["previous_response_id"]
        return translated

    @staticmethod
    def _coerce_message_text(content: object) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict) and item.get("type") in {"text", "input_text", "output_text"} and isinstance(item.get("text"), str):
                chunks.append(item["text"])
        return "\n".join(chunks)

    def _adapt_chat_completions_response(self, response: httpx.Response, original_payload: dict[str, Any], *, stream: bool) -> ProxyResult:
        if response.status_code >= 400:
            return ProxyResult(response.status_code, response.content, self._response_headers(response.headers))
        transcript = self._parse_sse(response.content.decode("utf-8", errors="replace"))
        if stream:
            return ProxyResult(200, self._build_chat_completion_stream(transcript, original_payload), {"content-type": "text/event-stream"})
        return ProxyResult(
            200,
            json.dumps(self._build_chat_completion_json(transcript, original_payload), ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json"},
        )

    def _parse_sse(self, text: str) -> dict[str, Any]:
        deltas: list[str] = []
        final_text = ""
        response_id = None
        model = None
        created_at = int(time.time())
        usage = None
        for chunk in text.split("\n\n"):
            chunk = chunk.strip()
            if not chunk:
                continue
            data_lines = [line[len("data: ") :] for line in chunk.splitlines() if line.startswith("data: ")]
            if not data_lines:
                continue
            try:
                payload = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                continue
            event_type = payload.get("type")
            if event_type == "response.created":
                response_obj = payload.get("response") or {}
                response_id = response_obj.get("id")
                model = response_obj.get("model")
                created_at = int(response_obj.get("created_at") or created_at)
            elif event_type == "response.output_text.delta":
                if isinstance(payload.get("delta"), str):
                    deltas.append(payload["delta"])
            elif event_type == "response.output_text.done":
                if isinstance(payload.get("text"), str):
                    final_text = payload["text"]
            elif event_type == "response.completed":
                response_obj = payload.get("response") or {}
                response_id = response_obj.get("id") or response_id
                model = response_obj.get("model") or model
                created_at = int(response_obj.get("created_at") or created_at)
                usage = response_obj.get("usage")
        content = "".join(deltas) or final_text
        return {
            "id": response_id or f"chatcmpl-{int(time.time())}",
            "model": model or "unknown",
            "created": created_at,
            "content": content,
            "deltas": deltas or ([final_text] if final_text else []),
            "usage": usage or {},
        }

    @staticmethod
    def _build_chat_completion_json(transcript: dict[str, Any], original_payload: dict[str, Any]) -> dict[str, Any]:
        usage = transcript.get("usage") or {}
        prompt_tokens = int(usage.get("input_tokens") or 0)
        completion_tokens = int(usage.get("output_tokens") or 0)
        return {
            "id": transcript["id"],
            "object": "chat.completion",
            "created": transcript["created"],
            "model": transcript.get("model") or original_payload.get("model"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": transcript.get("content") or ""}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens},
        }

    @staticmethod
    def _build_chat_completion_stream(transcript: dict[str, Any], original_payload: dict[str, Any]) -> bytes:
        chunks: list[str] = []
        created = transcript["created"]
        model = transcript.get("model") or original_payload.get("model")
        response_id = transcript["id"]
        deltas = transcript.get("deltas") or []
        for index, delta in enumerate(deltas):
            payload = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": delta} if index == 0 else {"content": delta}, "finish_reason": None}],
            }
            chunks.append(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")
        final_payload = {"id": response_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        chunks.append(f"data: {json.dumps(final_payload, ensure_ascii=False)}\n\n")
        chunks.append("data: [DONE]\n\n")
        return "".join(chunks).encode("utf-8")

    @staticmethod
    def _response_headers(headers: httpx.Headers) -> dict[str, str]:
        return {k: v for k, v in dict(headers).items() if k.lower() not in {"content-length", "transfer-encoding", "content-encoding"}}

    def _touch_api_key(self, api_key_row: dict[str, Any]) -> None:
        now = utc_now()
        with self.db.connect() as conn:
            conn.execute("UPDATE api_keys SET last_used_at = ?, updated_at = ? WHERE id = ?", (now, now, api_key_row["id"]))

    def _mark_account_success(self, account: dict[str, Any]) -> None:
        now = utc_now()
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE accounts SET failure_count = 0, last_success_at = ?, updated_at = ?, status = 'normal' WHERE id = ?",
                (now, now, account["id"]),
            )

    def _mark_account_failure(self, account: dict[str, Any], reason: str) -> None:
        now = utc_now()
        if reason in {"401", "403", "expired"}:
            status = "expired"
        elif reason == "429":
            status = "limited"
        else:
            status = account.get("status") or "normal"
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE accounts SET failure_count = failure_count + 1, last_failure_at = ?, status = ?, status_reason = ?, updated_at = ? WHERE id = ?",
                (now, status, f"proxy upstream failure: {reason}", now, account["id"]),
            )

    def _refresh_account(self, account: dict[str, Any]) -> dict[str, Any]:
        form = urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": account["refresh_token"],
                "client_id": CODEX_OAUTH_CLIENT_ID,
                "redirect_uri": CODEX_OAUTH_REDIRECT_URI,
            }
        )
        request = httpx.Request(
            method="POST",
            url=CODEX_OAUTH_TOKEN_URL,
            content=form.encode(),
            headers={"content-type": "application/x-www-form-urlencoded", "accept": "application/json"},
        )
        response = self._send(request)
        if response.status_code != 200:
            raise RuntimeError(f"refresh failed: {response.status_code}")
        payload = response.json()
        auth_json = json.loads(account["auth_raw"])
        tokens = auth_json.setdefault("tokens", {})
        tokens["access_token"] = payload["access_token"]
        tokens["refresh_token"] = payload.get("refresh_token") or account["refresh_token"]
        if payload.get("id_token"):
            tokens["id_token"] = payload["id_token"]
        auth_json["last_refresh"] = datetime.now(timezone.utc).isoformat()
        fields = extract_auth_fields(auth_json)
        now = utc_now()
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE accounts SET auth_raw = ?, access_token = ?, refresh_token = ?, expires_at = ?, status = 'normal', status_reason = ?, updated_at = ? WHERE id = ?",
                (fields["auth_raw"], fields["access_token"], fields["refresh_token"], fields["expires_at"], fields["status_reason"], now, account["id"]),
            )
            row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account["id"],)).fetchone()
            return dict(row)
