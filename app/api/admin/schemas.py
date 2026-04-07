from pydantic import BaseModel


class EmptyPayload(BaseModel):
    pass


class DeleteDocumentPayload(BaseModel):
    path: str


class EmployeeCreatePayload(BaseModel):
    nama: str
    departemen: str
    jabatan: str
    nomor_wa: str


class EmployeeItem(BaseModel):
    id: int
    nama: str
    departemen: str
    jabatan: str
    nomor_wa: str
    created_at: str
