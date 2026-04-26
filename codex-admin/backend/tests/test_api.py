from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(str(tmp_path / "codex-admin-test.sqlite3"))
    return TestClient(app)


def sample_auth(device_id: str = "dev-1") -> dict:
    return {
        "account_id": "acct-1",
        "device_id": device_id,
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_at": "2099-01-01T00:00:00+00:00",
    }


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
