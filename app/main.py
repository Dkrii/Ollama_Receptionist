import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routes.admin import router as admin_router
from api.routes.chat import router as chat_router
from api.routes.web import router as web_router


logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Virtual Receptionist Kiosk", version="0.1.0")
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(web_router)
app.include_router(chat_router)
app.include_router(admin_router)
