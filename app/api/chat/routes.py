from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api.chat.schemas import ChatRequest
from api.chat.service import ChatAppService


router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
def chat(payload: ChatRequest):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    return ChatAppService.ask(payload.message)


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    return StreamingResponse(
        ChatAppService.ask_stream(payload.message),
        media_type="application/x-ndjson",
    )
