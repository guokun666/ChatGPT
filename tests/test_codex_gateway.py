from datetime import datetime, timedelta, timezone

from revChatGPT.codex_gateway import (
    CodexAccount,
    CodexAccountPool,
    CodexScheduler,
    AccountStatus,
)


def make_account(account_id: str, device_id: str | None = None, status=AccountStatus.NORMAL):
    return CodexAccount(
        auth_raw='{"device_id":"%s","access_token":"at","refresh_token":"rt"}' % (device_id or account_id),
        account_id=account_id,
        device_id=device_id or account_id,
        access_token="at",
        refresh_token="rt",
        expire_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status=status,
    )


def test_scheduler_keeps_same_session_on_same_account():
    pool = CodexAccountPool([make_account("a1"), make_account("a2"), make_account("a3")])
    scheduler = CodexScheduler(pool)

    first = scheduler.select_account(session_id="session-1", api_key="key-a", client_ip="1.1.1.1", user_agent="ua")
    second = scheduler.select_account(session_id="session-1", api_key="key-a", client_ip="1.1.1.1", user_agent="ua")

    assert first.account_id == second.account_id


def test_scheduler_uses_api_key_when_session_id_is_missing():
    pool = CodexAccountPool([make_account("a1"), make_account("a2")])
    scheduler = CodexScheduler(pool)

    first = scheduler.select_account(api_key="global-key")
    second = scheduler.select_account(api_key="global-key")

    assert first.account_id == second.account_id


def test_limited_account_is_removed_from_active_ring():
    limited = make_account("limited", status=AccountStatus.LIMITED)
    normal = make_account("normal")
    pool = CodexAccountPool([limited, normal])
    scheduler = CodexScheduler(pool)

    selected = scheduler.select_account(session_id="any-session")

    assert selected.account_id == "normal"


def test_mark_failure_opens_circuit_after_threshold():
    account = make_account("a1")
    pool = CodexAccountPool([account], failure_threshold=2)

    pool.mark_failure("a1", reason="timeout")
    assert pool.get_account("a1").status == AccountStatus.NORMAL

    pool.mark_failure("a1", reason="timeout")
    assert pool.get_account("a1").status == AccountStatus.LIMITED
    assert pool.get_account("a1").circuit_open_until is not None


def test_expired_token_is_not_active():
    expired = make_account("expired")
    expired.expire_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    normal = make_account("normal")
    pool = CodexAccountPool([expired, normal])

    assert [account.account_id for account in pool.active_accounts()] == ["normal"]
