from typing import Any


def _start_contact_request(employee: dict, action: str) -> dict[str, Any]:
    return {
        "type": "notify",
        "status": "queued",
        "provider": "workflow",
        "employee": {
            "id": employee["id"],
            "nama": employee["nama"],
            "departemen": employee["departemen"],
            "jabatan": employee["jabatan"],
            "nomor_wa": employee["nomor_wa"],
        },
        "detail": "Permintaan kontak diterima dan sistem sedang mengecek ketersediaan karyawan.",
    }
