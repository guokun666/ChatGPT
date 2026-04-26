import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def fake_validation_runner(*, account, prompt: str, requested_model: str, reasoning_effort: str) -> dict:
    return {
        "ok": True,
        "validation_mode": "codex-cli",
        "requested_model": requested_model,
        "cli_model": "gpt-5.4",
        "reasoning_effort": reasoning_effort,
        "prompt": prompt,
        "assistant_message": f"真实 runner 测试响应：{prompt}",
    }


def make_client(tmp_path: Path, validation_runner=fake_validation_runner, upstream_handler=None) -> TestClient:
    app = create_app(
        str(tmp_path / "codex-admin-test.sqlite3"),
        validation_runner=validation_runner,
        upstream_sender=upstream_handler,
    )
    return TestClient(app)


def sample_auth(device_id: str = "dev-1") -> dict:
    return {
        "account_id": "acct-1",
        "device_id": device_id,
        "access_token": "***",
        "refresh_token": "***",
        "id_token": "***",
        "expires_at": "2099-01-01T00:00:00+00:00",
    }


def test_models_endpoint_reads_codex_model_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "models_cache.json"
    cache_path.write_text(
        '{"models":[{"slug":"gpt-5.5","display_name":"gpt-5.5","supported_reasoning_levels":[{"effort":"low"},{"effort":"xhigh"}],"visibility":"list"},{"slug":"hidden-model","display_name":"hidden","supported_reasoning_levels":[{"effort":"low"}],"visibility":"hide"}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_ADMIN_MODELS_CACHE", str(cache_path))
    client = make_client(tmp_path)

    response = client.get("/api/models")

    assert response.status_code == 200
    body = response.json()
    assert body["models"][0]["id"] == "gpt-5.5"
    assert body["models"][0]["reasoning_efforts"] == ["low", "xhigh"]
    assert "hidden-model" not in [item["id"] for item in body["models"]]
    assert body["default_model"] == "gpt-5.5"
    assert body["default_reasoning_effort"] == "low"
    assert body["source"] == str(cache_path)
    assert body["fetched_at"] is None


def test_models_endpoint_includes_codex_native_menu_models_when_cache_is_incomplete(tmp_path, monkeypatch):
    cache_path = tmp_path / "models_cache.json"
    cache_path.write_text(
        '{"models":[{"slug":"gpt-5.4","display_name":"GPT-5.4","supported_reasoning_levels":[{"effort":"medium"}],"visibility":"list"},{"slug":"gpt-5.4-mini","display_name":"GPT-5.4-Mini","supported_reasoning_levels":[{"effort":"medium"}],"visibility":"list"}],"fetched_at":"2026-04-26T17:15:53Z","client_version":"0.119.0"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_ADMIN_MODELS_CACHE", str(cache_path))
    client = make_client(tmp_path)

    response = client.get("/api/models")

    assert response.status_code == 200
    model_ids = [item["id"] for item in response.json()["models"]]
    assert model_ids[:3] == ["gpt-5.4", "gpt-5.2-codex", "gpt-5.1-codex-max"]
    assert "gpt-5.1-codex-mini" in model_ids
    assert len(model_ids) == len(set(model_ids))


def test_import_auth_json_creates_account_without_exposing_tokens(tmp_path):
    client = make_client(tmp_path)

    response = client.post("/api/accounts/import", json={"auth_json": sample_auth()})

    assert response.status_code == 201
    body = response.json()
    assert body["account_id"] == "acct-1"
    assert body["device_id"] == "dev-1"
    assert body["status"] == "normal"
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "auth_raw" not in body


def test_import_codex_cli_tokens_shape_without_top_level_device_id(tmp_path):
    client = make_client(tmp_path)
    auth_json = {
        "tokens": {
            "access_token": "***",
            "refresh_token": "***",
            "id_token": "***",
            "account_id": "acct-cli-1",
        },
        "last_refresh": "2026-01-01T00:00:00Z",
    }

    response = client.post("/api/accounts/import", json={"auth_json": auth_json})

    assert response.status_code == 201
    body = response.json()
    assert body["account_id"] == "acct-cli-1"
    assert body["device_id"] == "acct-cli-1"
    assert body["status_reason"] == "auth.json has no device_id; account_id is being used as the stable device key"


def test_import_rejects_auth_json_without_tokens(tmp_path):
    client = make_client(tmp_path)

    response = client.post("/api/accounts/import", json={"auth_json": {"account_id": "acct-no-token"}})

    assert response.status_code == 400
    assert "missing access_token" in response.json()["detail"]


def test_import_rejects_codex_auth_without_id_token(tmp_path):
    client = make_client(tmp_path)
    auth_json = {
        "tokens": {
            "access_token": "***",
            "refresh_token": "***",
            "account_id": "acct-no-id-token",
        }
    }

    response = client.post("/api/accounts/import", json={"auth_json": auth_json})

    assert response.status_code == 400
    assert "missing id_token" in response.json()["detail"]


def test_list_accounts_returns_status_summary(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/accounts/import", json={"auth_json": sample_auth("dev-1")})

    response = client.get("/api/accounts")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total"] == 1
    assert body["summary"]["normal"] == 1
    assert body["items"][0]["device_id"] == "dev-1"


def test_update_account_status_and_record_exception(tmp_path):
    client = make_client(tmp_path)
    created = client.post("/api/accounts/import", json={"auth_json": sample_auth()}).json()

    status_response = client.patch(
        f"/api/accounts/{created['id']}/status",
        json={"status": "limited", "reason": "429 quota"},
    )
    exception_response = client.post(
        "/api/exceptions",
        json={"account_id": created["id"], "level": "warning", "message": "429 quota", "detail": "rate limited"},
    )

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "limited"
    assert exception_response.status_code == 201
    exceptions = client.get("/api/exceptions").json()["items"]
    assert exceptions[0]["level"] == "warning"
    assert exceptions[0]["message"] == "429 quota"


def test_account_can_be_edited_without_exposing_secrets(tmp_path):
    client = make_client(tmp_path)
    created = client.post("/api/accounts/import", json={"auth_json": sample_auth()}).json()

    response = client.patch(
        f"/api/accounts/{created['id']}",
        json={
            "account_id": "acct-edited",
            "device_id": "dev-edited",
            "expires_at": "2099-02-01T00:00:00+00:00",
            "status": "disabled",
            "status_reason": "manual maintenance",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["account_id"] == "acct-edited"
    assert body["device_id"] == "dev-edited"
    assert body["expires_at"] == "2099-02-01T00:00:00+00:00"
    assert body["status"] == "disabled"
    assert body["status_reason"] == "manual maintenance"
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "auth_raw" not in body


def test_account_edit_can_update_auth_json_without_returning_secrets(tmp_path):
    client = make_client(tmp_path)
    created = client.post("/api/accounts/import", json={"auth_json": sample_auth()}).json()
    new_auth = {
        "tokens": {
            "access_token": "***",
            "refresh_token": "***",
            "id_token": "***",
            "account_id": "acct-from-edit-auth",
            "device_id": "dev-from-edit-auth",
        },
        "expires_at": "2099-03-01T00:00:00+00:00",
    }

    response = client.patch(f"/api/accounts/{created['id']}", json={"auth_json": new_auth})

    assert response.status_code == 200
    body = response.json()
    assert body["account_id"] == "acct-from-edit-auth"
    assert body["device_id"] == "dev-from-edit-auth"
    assert body["expires_at"] == "2099-03-01T00:00:00+00:00"
    assert body["status_reason"] is None
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "auth_raw" not in body


def test_account_edit_rejects_invalid_auth_json(tmp_path):
    client = make_client(tmp_path)
    created = client.post("/api/accounts/import", json={"auth_json": sample_auth()}).json()

    response = client.patch(f"/api/accounts/{created['id']}", json={"auth_json": {"account_id": "acct-only"}})

    assert response.status_code == 400
    assert "missing access_token" in response.json()["detail"]


def test_account_auth_can_run_default_validation_chat(tmp_path):
    client = make_client(tmp_path)
    created = client.post("/api/accounts/import", json={"auth_json": sample_auth()}).json()

    response = client.post(f"/api/accounts/{created['id']}/test", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["target_type"] == "account"
    assert body["target_id"] == created["id"]
    assert body["prompt"] == "你好。"
    assert body["requested_model"] == "codex-code"
    assert body["reasoning_effort"] == "low"
    assert body["validation_mode"] == "codex-cli"
    assert body["ok"] is True
    assert "你好" in body["assistant_message"]
    assert "access_token" not in str(body)
    assert "refresh_token" not in str(body)


def test_account_auth_can_choose_model_and_reasoning_effort(tmp_path):
    client = make_client(tmp_path)
    created = client.post("/api/accounts/import", json={"auth_json": sample_auth()}).json()

    response = client.post(
        f"/api/accounts/{created['id']}/test",
        json={"prompt": "解释一下缓存命中", "model": "gpt-5.4", "reasoning_effort": "medium"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["prompt"] == "解释一下缓存命中"
    assert body["requested_model"] == "gpt-5.4"
    assert body["reasoning_effort"] == "medium"


def test_account_auth_validation_rejects_unhealthy_account(tmp_path):
    client = make_client(tmp_path)
    created = client.post("/api/accounts/import", json={"auth_json": sample_auth()}).json()
    client.patch(f"/api/accounts/{created['id']}/status", json={"status": "expired", "reason": "manual expired"})

    response = client.post(f"/api/accounts/{created['id']}/test", json={"prompt": "你好。"})

    assert response.status_code == 400
    assert "not normal" in response.json()["detail"]


def test_account_delete_hides_from_default_list_and_can_be_restored(tmp_path):
    client = make_client(tmp_path)
    created = client.post("/api/accounts/import", json={"auth_json": sample_auth()}).json()

    deleted = client.delete(f"/api/accounts/{created['id']}")

    assert deleted.status_code == 204
    assert client.get("/api/accounts").json()["items"] == []
    with_deleted = client.get("/api/accounts?include_deleted=true").json()["items"]
    assert len(with_deleted) == 1
    assert with_deleted[0]["deleted_at"] is not None
    assert with_deleted[0]["deleted_reason"] == "manual delete"

    restored = client.post(f"/api/accounts/{created['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None
    assert client.get("/api/accounts").json()["items"][0]["id"] == created["id"]


def test_research_notes_can_be_recorded_and_listed(tmp_path):
    client = make_client(tmp_path)

    created = client.post(
        "/api/research-notes",
        json={"title": "native auth validation", "status": "pending", "content": "Need a real auth.json to verify."},
    )
    listed = client.get("/api/research-notes")

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json()["items"][0]["title"] == "native auth validation"
    assert listed.json()["items"][0]["status"] == "pending"


def test_api_keys_can_be_created_listed_disabled_and_deleted(tmp_path):
    client = make_client(tmp_path)

    created = client.post(
        "/api/api-keys",
        json={"name": "client-a", "status": "active", "rate_limit_per_minute": 60, "model_scopes": ["codex-code"]},
    )

    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "client-a"
    assert body["key"].startswith("ck-")
    assert body["key_preview"].startswith("ck-")
    assert body["status"] == "active"
    assert body["model_scopes"] == ["codex-code"]

    listed = client.get("/api/api-keys").json()["items"]
    assert listed[0]["name"] == "client-a"
    assert "key" not in listed[0]

    disabled = client.patch(f"/api/api-keys/{body['id']}", json={"status": "disabled"})
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"

    deleted = client.delete(f"/api/api-keys/{body['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/api-keys").json()["items"] == []


def test_api_key_can_run_default_validation_chat(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/accounts/import", json={"auth_json": sample_auth()})
    created = client.post(
        "/api/api-keys",
        json={"name": "client-a", "status": "active", "rate_limit_per_minute": 60, "model_scopes": ["codex-code"]},
    ).json()

    response = client.post(f"/api/api-keys/{created['id']}/test", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["target_type"] == "api_key"
    assert body["target_id"] == created["id"]
    assert body["prompt"] == "你好。"
    assert body["requested_model"] == "codex-code"
    assert body["reasoning_effort"] == "low"
    assert body["validation_mode"] == "codex-cli"
    assert body["ok"] is True
    assert "你好" in body["assistant_message"]
    assert created["key"] not in str(body)


def test_api_key_validation_rejects_disabled_key(tmp_path):
    client = make_client(tmp_path)
    created = client.post("/api/api-keys", json={"name": "client-a", "status": "disabled"}).json()

    response = client.post(f"/api/api-keys/{created['id']}/test", json={"prompt": "你好。"})

    assert response.status_code == 400
    assert "not active" in response.json()["detail"]


def test_api_key_validation_rejects_model_outside_scope_with_clear_allowed_scopes(tmp_path):
    client = make_client(tmp_path)
    created = client.post(
        "/api/api-keys",
        json={"name": "client-a", "status": "active", "model_scopes": ["code-mini"]},
    ).json()

    response = client.post(f"/api/api-keys/{created['id']}/test", json={"model": "gpt-5.4-mini"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "API key does not allow model gpt-5.4-mini" in detail
    assert "allowed scopes: code-mini" in detail
    assert "edit this API key" in detail


def test_api_key_model_scopes_can_be_updated_to_dynamic_model(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/accounts/import", json={"auth_json": sample_auth()})
    created = client.post(
        "/api/api-keys",
        json={"name": "client-a", "status": "active", "model_scopes": ["code-mini"]},
    ).json()

    updated = client.patch(f"/api/api-keys/{created['id']}", json={"model_scopes": ["gpt-5.4-mini"]})
    response = client.post(f"/api/api-keys/{created['id']}/test", json={"model": "gpt-5.4-mini"})

    assert updated.status_code == 200
    assert updated.json()["model_scopes"] == ["gpt-5.4-mini"]
    assert response.status_code == 200
    assert response.json()["requested_model"] == "gpt-5.4-mini"


def test_v1_models_requires_external_api_key(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/v1/models")

    assert response.status_code == 401


def test_v1_models_uses_active_api_key_and_model_scopes(tmp_path):
    client = make_client(tmp_path)
    created = client.post(
        "/api/api-keys",
        json={"name": "client-a", "status": "active", "model_scopes": ["gpt-5.4", "gpt-5.2-codex"]},
    ).json()

    response = client.get("/v1/models", headers={"Authorization": f"Bearer {created['key']}"})

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == ["gpt-5.4", "gpt-5.2-codex"]


def test_v1_chat_completions_proxies_with_managed_api_key_and_account(tmp_path):
    import httpx

    upstream_calls = []

    def fake_upstream(request: httpx.Request) -> httpx.Response:
        upstream_calls.append(request)
        assert request.url.path == "/backend-api/codex/responses"
        payload = json.loads(request.content.decode())
        assert payload["model"] == "gpt-5.4"
        assert payload["store"] is False
        assert payload["stream"] is True
        assert payload["input"][0]["content"][0]["text"] == "Reply with ok"
        assert request.headers["authorization"] == "Bearer ***"
        assert request.headers["chatgpt-account-id"] == "acct-1"
        body = "\n\n".join([
            'data: {"type":"response.created","response":{"id":"resp_1","model":"gpt-5.4","created_at":123}}',
            'data: {"type":"response.output_text.delta","delta":"ok"}',
            'data: {"type":"response.completed","response":{"id":"resp_1","model":"gpt-5.4","created_at":123,"usage":{"input_tokens":4,"output_tokens":1}}}',
        ])
        return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"}, request=request)

    client = make_client(tmp_path, upstream_handler=fake_upstream)
    client.post("/api/accounts/import", json={"auth_json": sample_auth()})
    created = client.post("/api/api-keys", json={"name": "client-a", "status": "active"}).json()

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {created['key']}", "X-Session-Id": "session-a"},
        json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "Reply with ok"}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "ok"
    assert body["usage"] == {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}
    assert len(upstream_calls) == 1


def test_dashboard_summary_combines_accounts_notes_exceptions_and_api_keys(tmp_path):
    client = make_client(tmp_path)
    account = client.post("/api/accounts/import", json={"auth_json": sample_auth()}).json()
    client.patch(f"/api/accounts/{account['id']}/status", json={"status": "banned", "reason": "risk"})
    client.post("/api/research-notes", json={"title": "SDK check", "status": "done", "content": "checked"})
    client.post("/api/exceptions", json={"account_id": account["id"], "level": "error", "message": "risk", "detail": "banned"})
    client.post("/api/api-keys", json={"name": "client-a", "status": "active", "rate_limit_per_minute": 60})

    response = client.get("/api/dashboard")

    assert response.status_code == 200
    body = response.json()
    assert body["accounts"]["total"] == 1
    assert body["accounts"]["banned"] == 1
    assert body["research_notes"] == {"total": 1, "done": 1, "pending": 0, "blocked": 0}
    assert body["exceptions"]["total"] == 1
    assert body["exceptions"]["error"] == 1
    assert body["api_keys"] == {"total": 1, "active": 1, "disabled": 0}
