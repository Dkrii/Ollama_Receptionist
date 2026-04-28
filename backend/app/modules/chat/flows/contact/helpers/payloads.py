from typing import Any

from .employees import _normalize_department_label


def _build_stage(stage: str, flow_context: dict, **kwargs: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"stage": stage, "context": flow_context}
    result.update(kwargs)
    return result


def _build_contact_message_text(employee: dict[str, Any], visitor_name: str, visitor_goal: str) -> str:
    employee_name = str(employee.get("nama") or "Bapak/Ibu").strip() or "Bapak/Ibu"

    lines = [
        "Notifikasi Virtual Receptionist",
        f"Halo {employee_name}, ada tamu yang ingin menghubungi Anda.",
        f"Nama Tamu: {visitor_name}",
        f"Keperluan: {visitor_goal}",
        "Mohon tindak lanjut saat Anda tersedia.",
        "Terima kasih.",
    ]
    return "\n".join(lines)


def _unpack_ctx(ctx: dict) -> tuple:
    return (
        ctx["message"],
        ctx["conversation_id"],
        ctx["safe_flow_state"],
        ctx["flow_context"],
        ctx["action"],
    )


def _extract_session(safe_flow_state: dict) -> tuple[dict, str, str]:
    selected = safe_flow_state.get("selected") or {}
    target_kind = str(safe_flow_state.get("target_kind") or "person").strip().lower()
    department = _normalize_department_label(str(safe_flow_state.get("department") or ""))
    return selected, target_kind, department
