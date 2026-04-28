from typing import Any

from modules.contacts.call.api_service import ContactCallService


def _start_contact_request(employee: dict, action: str) -> dict[str, Any]:
    if action == "call":
        stored_call = ContactCallService.create_session_for_employee(employee)
        return {
            "type": "start_two_way_call",
            "status": str((stored_call or {}).get("call_status") or "preparing"),
            "provider": str((stored_call or {}).get("call_provider") or "twilio"),
            "employee": {
                "id": employee["id"],
                "nama": employee["nama"],
                "departemen": employee["departemen"],
                "jabatan": employee["jabatan"],
                "nomor_wa": employee["nomor_wa"],
            },
            "detail": str((stored_call or {}).get("call_detail") or ""),
            "call_session_id": str((stored_call or {}).get("call_session_id") or ""),
            "dev_identity": str((stored_call or {}).get("dev_identity") or ""),
            "provider_payload": (stored_call or {}).get("provider_payload"),
            "call": stored_call,
        }

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
