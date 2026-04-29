from pydantic import BaseModel, Field, field_validator
from typing import Any


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    history: list[ChatTurn] = Field(default_factory=list)
    flow_state: dict[str, Any] = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message tidak boleh kosong")
        return v


class PendingAction(BaseModel):
    type: str = "contact_message"
    target_employee_id: int | None = None
    target_label: str = ""
    confirmed: bool = False
    visitor_name: str = ""
    visitor_goal: str = ""
