from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from schemas.chat import ChatRequest
from services.chat_service import ChatService


router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
def chat(payload: ChatRequest):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    return ChatService.ask(payload.message)


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    return StreamingResponse(
        ChatService.ask_stream(payload.message),
        media_type="application/x-ndjson",
    )
