import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.admin_routes import router as admin_router
from api.chat_routes import router as chat_router
from api.contact_routes import router as contact_call_router
from api.web_routes import router as web_router
from storage.admin_repository import AdminRepository
from storage.chat_repository import ChatRepository
from middleware import RequestLoggerMiddleware


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
)

BASE_DIR = Path(__file__).resolve().parent


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

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(web_router)
app.include_router(chat_router)
app.include_router(contact_call_router)
app.include_router(admin_router)
