from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AccountStatus = Literal["normal", "limited", "banned", "expired", "disabled"]
NoteStatus = Literal["pending", "done", "blocked"]
ExceptionLevel = Literal["info", "warning", "error"]


class ImportAuthRequest(BaseModel):
    auth_json: dict[str, Any]


class UpdateAccountStatusRequest(BaseModel):
    status: AccountStatus
    reason: str = ""


class ResearchNoteCreate(BaseModel):
    title: str = Field(min_length=1)
    status: NoteStatus = "pending"
    content: str = ""


class ExceptionCreate(BaseModel):
    account_id: int | None = None
    level: ExceptionLevel
    message: str = Field(min_length=1)
    detail: str = ""
