from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from modules.admin.schemas import DeleteDocumentPayload
from modules.admin.service import AdminAppService


router = APIRouter(prefix="/api", tags=["admin"])


@router.post("/reindex")
def reindex():
    try:
        result = AdminAppService.reindex()
        return JSONResponse(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/admin/upload-documents")
def upload_documents(files: list[UploadFile] = File(...)):
    try:
        return JSONResponse(AdminAppService.upload_documents(files))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/admin/status")
def monitoring_status():
    try:
        return JSONResponse(AdminAppService.monitoring_status())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/admin/knowledge-summary")
def knowledge_summary():
    try:
        return JSONResponse(AdminAppService.knowledge_summary())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/admin/knowledge-documents")
def knowledge_documents(page: int = 1, limit: int = 10, search: str = "", status: str = "all"):
    try:
        return JSONResponse(
            AdminAppService.knowledge_documents(
                page=page,
                limit=limit,
                search=search,
                status=status,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/admin/contact-messages")
def contact_messages(page: int = 1, limit: int = 10, search: str = "", status: str = "all"):
    try:
        return JSONResponse(
            AdminAppService.contact_messages(
                page=page,
                limit=limit,
                search=search,
                status=status,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/admin/documents")
def delete_document(payload: DeleteDocumentPayload):
    try:
        return JSONResponse(AdminAppService.delete_document(payload.path))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
