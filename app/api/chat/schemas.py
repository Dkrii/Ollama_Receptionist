from pydantic import BaseModel, Field
from typing import Any


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    history: list[ChatTurn] = Field(default_factory=list)
    flow_state: dict[str, Any] = Field(default_factory=dict)


class ContactFlowRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    history: list[ChatTurn] = Field(default_factory=list)
    flow_state: dict[str, Any] = Field(default_factory=dict)
