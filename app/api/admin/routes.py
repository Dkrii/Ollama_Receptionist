from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from api.admin.schemas import DeleteDocumentPayload, EmployeeCreatePayload
from api.admin.service import AdminAppService


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


@router.get("/admin/employees")
def list_employees():
    try:
        return JSONResponse(AdminAppService.list_employees())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/admin/employees")
def create_employee(payload: EmployeeCreatePayload):
    try:
        result = AdminAppService.create_employee(
            nama=payload.nama,
            departemen=payload.departemen,
            jabatan=payload.jabatan,
            nomor_wa=payload.nomor_wa,
        )
        return JSONResponse(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/admin/contact-messages")
def list_contact_messages(limit: int = Query(default=50, ge=1, le=200)):
    try:
        return JSONResponse(AdminAppService.list_contact_messages(limit=limit))
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
