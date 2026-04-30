from __future__ import annotations

from typing import NotRequired, TypedDict


class EmployeeRecord(TypedDict):
    id: int
    nama: str
    departemen: str
    division: NotRequired[str]
    section: NotRequired[str]
    jabatan: str
    nomor_wa: str
    source: str
