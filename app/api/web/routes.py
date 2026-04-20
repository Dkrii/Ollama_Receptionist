from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from api.web.service import WebPageService


from config import settings

BASE_DIR = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
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
