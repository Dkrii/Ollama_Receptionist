from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from api.web.service import WebPageService


templates = Jinja2Templates(directory="templates")
router = APIRouter(tags=["web"])


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(WebPageService.home_template(), {"request": request})

@router.get("/dev", response_class=HTMLResponse)
def dev(request: Request):
    return templates.TemplateResponse(WebPageService.dev_template(), {"request": request})


@router.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    return templates.TemplateResponse(WebPageService.admin_template(), {"request": request})


@router.get("/health")
def health():
    return {"status": "ok"}
