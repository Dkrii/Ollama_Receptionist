from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

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
