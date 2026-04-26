from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AccountStatus = Literal["normal", "limited", "banned", "expired", "disabled"]
NoteStatus = Literal["pending", "done", "blocked"]
ExceptionLevel = Literal["info", "warning", "error"]
ApiKeyStatus = Literal["active", "disabled"]
ReasoningEffort = Literal["low", "medium", "high", "xhigh"]


class ImportAuthRequest(BaseModel):
    auth_json: dict[str, Any]


class UpdateAccountStatusRequest(BaseModel):
    status: AccountStatus
    reason: str = ""


class AccountUpdate(BaseModel):
    account_id: str | None = None
    device_id: str | None = None
    expires_at: str | None = None
    status: AccountStatus | None = None
    status_reason: str | None = None
    auth_json: dict[str, Any] | None = None


class ResearchNoteCreate(BaseModel):
    title: str = Field(min_length=1)
    status: NoteStatus = "pending"
    content: str = ""


class ExceptionCreate(BaseModel):
    account_id: int | None = None
    level: ExceptionLevel
    message: str = Field(min_length=1)
    detail: str = ""


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1)
    status: ApiKeyStatus = "active"
    rate_limit_per_minute: int | None = None
    model_scopes: list[str] = Field(default_factory=list)


class ApiKeyUpdate(BaseModel):
    name: str | None = None
    status: ApiKeyStatus | None = None
    rate_limit_per_minute: int | None = None
    model_scopes: list[str] | None = None


class ValidationChatRequest(BaseModel):
    prompt: str = "你好。"
    model: str = "codex-code"
    reasoning_effort: ReasoningEffort = "low"
