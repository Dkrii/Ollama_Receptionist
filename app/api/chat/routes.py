from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.chat.schemas import ChatRequest
from api.chat.service import ChatAppService


router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest):
    return StreamingResponse(
        ChatAppService.ask_stream(
            payload.message,
            conversation_id=payload.conversation_id,
            history=[item.model_dump() for item in payload.history],
            flow_state=payload.flow_state,
        ),
        media_type="application/x-ndjson",
    )
