from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api.chat.schemas import ChatRequest, ContactFlowRequest
from api.chat.service import ChatAppService


router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
def chat(payload: ChatRequest):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    return ChatAppService.ask(
        payload.message,
        conversation_id=payload.conversation_id,
        history=[item.model_dump() for item in payload.history],
        flow_state=payload.flow_state,
    )


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    return StreamingResponse(
        ChatAppService.ask_stream(
            payload.message,
            conversation_id=payload.conversation_id,
            history=[item.model_dump() for item in payload.history],
            flow_state=payload.flow_state,
        ),
        media_type="application/x-ndjson",
    )


@router.post("/chat/contact-flow")
def chat_contact_flow(payload: ContactFlowRequest):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    return ChatAppService.handle_contact_flow(
        payload.message,
        conversation_id=payload.conversation_id,
        history=[item.model_dump() for item in payload.history],
        flow_state=payload.flow_state,
    )
