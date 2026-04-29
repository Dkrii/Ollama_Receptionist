from __future__ import annotations

from typing import TypedDict


class EmployeeRecord(TypedDict):
    id: int
    nama: str
    departemen: str
    jabatan: str
    nomor_wa: str
    source: str
