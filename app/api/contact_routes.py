from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from api.schemas.contact import ContactCallClientStatusRequest, ContactCallSessionRequest
from contacts.call.api_service import ContactCallService


router = APIRouter(prefix="/api/contact/call", tags=["contact-call"])


@router.post("/session")
def create_call_session(payload: ContactCallSessionRequest):
    try:
        stored_call = ContactCallService.create_session_for_employee(payload.employee.model_dump())
        return JSONResponse(
            {
                "call_session_id": str(stored_call.get("call_session_id") or ""),
                "status": str(stored_call.get("call_status") or "preparing"),
                "provider": str(stored_call.get("call_provider") or "dummy"),
                "dev_identity": str(stored_call.get("dev_identity") or ""),
                "call": stored_call,
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/token")
def issue_call_token(request: Request, call_session_id: str = Query(..., min_length=8)):
    try:
        return JSONResponse(ContactCallService.issue_access_token(call_session_id, request=request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/status")
def get_call_status(call_session_id: str = Query(..., min_length=8)):
    try:
        return JSONResponse({"ok": True, "call": ContactCallService.get_status(call_session_id)})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/fail")
async def fail_call(request: Request):
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Payload gagal dibaca.") from exc

    try:
        call_session_id = str((payload or {}).get("call_session_id") or "").strip()
        if len(call_session_id) < 8:
            raise RuntimeError("call_session_id wajib dikirim.")
        updated = ContactCallService.fail_from_client(
            call_session_id,
            status=str((payload or {}).get("status") or "failed"),
            reason=str((payload or {}).get("reason") or "client_error"),
            request=request,
        )
        return JSONResponse({"ok": True, "call": updated})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/client-status")
def sync_client_call_status(payload: ContactCallClientStatusRequest, request: Request):
    try:
        updated = ContactCallService.sync_client_status(payload.model_dump(), request=request)
        return JSONResponse({"ok": True, "call": updated})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.api_route("/twiml", methods=["GET", "POST"])
async def contact_call_twiml(request: Request, call_session_id: str | None = Query(None, min_length=8)):
    try:
        xml = await ContactCallService.render_twiml(call_session_id, request)
        return Response(content=xml, media_type="application/xml")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/status")
async def contact_call_status(request: Request, call_session_id: str | None = Query(None, min_length=8)):
    try:
        updated = await ContactCallService.sync_status(call_session_id, request)
        return JSONResponse({"ok": True, "call": updated})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
