from pydantic import BaseModel


class ContactCallEmployeePayload(BaseModel):
    id: int
    nama: str
    departemen: str = ""
    jabatan: str = ""
    nomor_wa: str = ""


class ContactCallSessionRequest(BaseModel):
    employee: ContactCallEmployeePayload
