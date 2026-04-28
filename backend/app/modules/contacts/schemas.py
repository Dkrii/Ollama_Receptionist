from typing import Any

from pydantic import BaseModel


class ContactCallEmployeePayload(BaseModel):
    id: int
    nama: str
    departemen: str = ""
    jabatan: str = ""
    nomor_wa: str = ""


class ContactCallSessionRequest(BaseModel):
    employee: ContactCallEmployeePayload


class ContactCallClientStatusRequest(BaseModel):
    call_session_id: str
    provider: str = ""
    status: str
    provider_call_id: str = ""
    provider_payload: dict[str, Any] | list[Any] | str | None = None
