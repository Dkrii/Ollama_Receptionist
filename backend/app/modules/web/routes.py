from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import settings
from modules.web.service import WebPageService

templates = Jinja2Templates(directory=str(settings.frontend_src_dir / "templates"))
router = APIRouter(tags=["web"])


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(WebPageService.home_template(), {"request": request, "app_env": settings.app_env})


@router.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    return templates.TemplateResponse(WebPageService.admin_template(), {"request": request, "app_env": settings.app_env})


@router.get("/health")
def health():
    return {"status": "ok"}
