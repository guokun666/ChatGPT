from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Iterable, List, Optional


class AccountStatus(str, Enum):
    NORMAL = "normal"
    LIMITED = "limited"
    BANNED = "banned"
    EXPIRED = "expired"


@dataclass
class CodexAccount:
    auth_raw: str
    account_id: str
    device_id: str
    access_token: str
    refresh_token: str
    expire_at: datetime
    status: AccountStatus = AccountStatus.NORMAL
    failure_count: int = 0
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    circuit_open_until: Optional[datetime] = None

    @classmethod
    def from_auth_json(cls, auth_raw: str) -> "CodexAccount":
        data = json.loads(auth_raw)
        device_id = data.get("device_id") or data.get("deviceId") or data.get("deviceID")
        access_token = data.get("access_token") or data.get("accessToken")
        refresh_token = data.get("refresh_token") or data.get("refreshToken")
        account_id = data.get("account_id") or data.get("user_id") or data.get("sub") or device_id
        expires_at = data.get("expire_at") or data.get("expires_at") or data.get("expiresAt")

        if not device_id:
            raise ValueError("auth.json is missing device_id")
        if not access_token:
            raise ValueError("auth.json is missing access_token")
        if not refresh_token:
            raise ValueError("auth.json is missing refresh_token")

        if isinstance(expires_at, (int, float)):
            expire_at = datetime.fromtimestamp(expires_at, timezone.utc)
        elif isinstance(expires_at, str):
            expire_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        else:
            expire_at = datetime.now(timezone.utc) + timedelta(minutes=30)

        return cls(
            auth_raw=auth_raw,
            account_id=account_id,
            device_id=device_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expire_at=expire_at,
        )

    def is_token_expired(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return self.expire_at <= now

    def is_active(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if self.status != AccountStatus.NORMAL:
            return False
        if self.is_token_expired(now):
            return False
        if self.circuit_open_until and self.circuit_open_until > now:
            return False
        return True


class CodexAccountPool:
    def __init__(
        self,
        accounts: Iterable[CodexAccount],
        failure_threshold: int = 3,
        circuit_break_seconds: int = 300,
    ) -> None:
        self.accounts: List[CodexAccount] = list(accounts)
        self.failure_threshold = failure_threshold
        self.circuit_break_seconds = circuit_break_seconds

    def get_account(self, account_id: str) -> CodexAccount:
        for account in self.accounts:
            if account.account_id == account_id:
                return account
        raise KeyError(account_id)

    def active_accounts(self, now: Optional[datetime] = None) -> List[CodexAccount]:
        return [account for account in self.accounts if account.is_active(now)]

    def mark_success(self, account_id: str) -> None:
        account = self.get_account(account_id)
        account.failure_count = 0
        account.last_success_at = datetime.now(timezone.utc)
        account.circuit_open_until = None
        if account.status == AccountStatus.LIMITED:
            account.status = AccountStatus.NORMAL

    def mark_failure(self, account_id: str, reason: str = "") -> None:
        account = self.get_account(account_id)
        account.failure_count += 1
        account.last_failure_at = datetime.now(timezone.utc)
        if reason in {"401", "unauthorized", "expired"}:
            account.status = AccountStatus.EXPIRED
        elif reason in {"banned", "risk_control"}:
            account.status = AccountStatus.BANNED
        elif account.failure_count >= self.failure_threshold or reason in {"429", "rate_limited"}:
            account.status = AccountStatus.LIMITED
            account.circuit_open_until = datetime.now(timezone.utc) + timedelta(
                seconds=self.circuit_break_seconds,
            )


class CodexScheduler:
    def __init__(self, pool: CodexAccountPool) -> None:
        self.pool = pool

    def select_account(
        self,
        *,
        session_id: Optional[str] = None,
        api_key: Optional[str] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> CodexAccount:
        active = self.pool.active_accounts()
        if not active:
            raise RuntimeError("no active Codex account is available")

        identity = self._routing_identity(session_id, api_key, client_ip, user_agent)
        best_score = None
        best_account = None
        for account in active:
            score = self._hash_score(f"{identity}:{account.account_id}:{account.device_id}")
            if best_score is None or score > best_score:
                best_score = score
                best_account = account
        assert best_account is not None
        return best_account

    @staticmethod
    def _routing_identity(
        session_id: Optional[str],
        api_key: Optional[str],
        client_ip: Optional[str],
        user_agent: Optional[str],
    ) -> str:
        if session_id:
            return f"session:{session_id}"
        if api_key:
            return f"api-key:{api_key}"
        return f"fingerprint:{client_ip or ''}:{user_agent or ''}"

    @staticmethod
    def _hash_score(value: str) -> int:
        return int(hashlib.sha256(value.encode("utf-8")).hexdigest(), 16)
