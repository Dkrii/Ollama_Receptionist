import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import settings
from middleware import RequestLoggerMiddleware
from modules.admin.repository import AdminRepository
from modules.admin.routes import router as admin_router
from modules.chat.controller import router as chat_router
from modules.chat.repository import ChatRepository
from modules.web.routes import router as web_router


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
)

@asynccontextmanager
async def lifespan(_: FastAPI):
    ChatRepository.initialize()
    AdminRepository.initialize()
    try:
        ChatRepository.cleanup_expired_transcripts()
    except Exception:
        logging.exception("chat.sqlite.cleanup skipped")
    yield


app = FastAPI(title="Virtual Receptionist Kiosk", version="0.1.0", lifespan=lifespan)

app.add_middleware(RequestLoggerMiddleware)

app.mount("/static", StaticFiles(directory=str(settings.frontend_src_dir / "static")), name="static")

app.include_router(web_router)
app.include_router(chat_router)
app.include_router(admin_router)
