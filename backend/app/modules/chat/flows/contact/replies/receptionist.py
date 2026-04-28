from typing import Any

from modules.chat.shared.transcript import store_chat_message
from modules.chat.flows.contact.helpers.employees import (
    _format_employee_contact_target,
    _format_employee_option_label,
)
from modules.chat.flows.contact.helpers.payloads import _build_stage


def _build_disambiguation_prompt(candidates: list[dict], prefix: str) -> str:
    candidate_names = [
        _format_employee_option_label(item)
        for item in candidates
        if isinstance(item, dict) and item.get("nama")
    ]
    if not candidate_names:
        return prefix + " Silakan sebutkan nama lengkap atau divisi yang Anda maksud."
    if len(candidate_names) == 1:
        return prefix + f" Apakah {candidate_names[0]}?"
    if len(candidate_names) == 2:
        listed_names = f"{candidate_names[0]} atau {candidate_names[1]}"
    else:
        listed_names = ", ".join(candidate_names[:-1]) + f", atau {candidate_names[-1]}"
    return prefix + f" Apakah {listed_names}?"

def _build_cancel_contact_answer(selected: dict | None, target_kind: str, department: str) -> str:
    if target_kind == "department" and department:
        return f"Baik, saya batalkan permintaan untuk menghubungi tim {department}."

    if isinstance(selected, dict) and selected.get("nama") and selected.get("departemen"):
        return (
            f"Baik, saya batalkan dulu permintaan untuk menghubungi "
            f"{selected['nama']} ({selected['departemen']})."
        )

    return "Baik, saya batalkan permintaan kontaknya."

def _build_call_unavailable_message_answer(selected: dict) -> str:
    return (
        f"{selected['nama']} tidak bisa dihubungi saat ini. "
        "Saya bisa bantu tinggalkan pesan. Mohon sebutkan nama Anda terlebih dahulu."
    )

def _build_follow_up_prompt(
    stage: str,
    *,
    eyebrow: str,
    title: str,
    message: str,
    tone: str = "prompt",
) -> dict[str, Any]:
    return {
        "type": "prompt",
        "stage": stage,
        "eyebrow": eyebrow,
        "title": title,
        "message": message,
        "tone": tone,
    }

def _build_confirmation_follow_up(selected: dict, target_kind: str = "person", department: str = "") -> dict[str, Any]:
    if target_kind == "department" and department:
        target_label = f"tim {department}"
    else:
        target_label = _format_employee_contact_target(selected) if isinstance(selected, dict) else "karyawan terkait"

    return _build_follow_up_prompt(
        "await_confirmation",
        eyebrow="Konfirmasi",
        title=f"Siap menghubungi {target_label}",
        message="Silakan jawab ya untuk melanjutkan atau tidak untuk membatalkan.",
        tone="prompt",
    )

def _build_disambiguation_follow_up(candidates: list[dict]) -> dict[str, Any]:
    labels = [
        _format_employee_option_label(candidate)
        for candidate in candidates[:3]
        if isinstance(candidate, dict) and candidate.get("nama")
    ]
    if not labels:
        message = "Silakan sebutkan nama lengkap atau divisi yang Anda maksud."
    elif len(labels) == 1:
        message = f"Silakan pastikan apakah yang Anda maksud adalah {labels[0]}."
    elif len(labels) == 2:
        message = f"Sebutkan nama yang paling sesuai: {labels[0]} atau {labels[1]}."
    else:
        message = f"Sebutkan nama yang paling sesuai: {labels[0]}, {labels[1]}, atau {labels[2]}."
    return _build_follow_up_prompt(
        "await_disambiguation",
        eyebrow="Pilihan kontak",
        title="Siapa yang Anda maksud?",
        message=message,
        tone="prompt",
    )

def _build_message_name_follow_up(selected: dict) -> dict[str, Any]:
    employee_name = str((selected or {}).get("nama") or "karyawan").strip()
    return _build_follow_up_prompt(
        "await_message_name",
        eyebrow="Tinggalkan pesan",
        title=f"Nama Anda diperlukan untuk pesan ke {employee_name}",
        message="Silakan sebutkan nama Anda terlebih dahulu agar pesan bisa dicatat.",
        tone="prompt",
    )

def _build_message_goal_follow_up(selected: dict) -> dict[str, Any]:
    employee_name = str((selected or {}).get("nama") or "karyawan").strip()
    return _build_follow_up_prompt(
        "await_message_goal",
        eyebrow="Tinggalkan pesan",
        title=f"Sampaikan keperluan Anda untuk {employee_name}",
        message="Silakan jelaskan tujuan atau keperluan Anda dengan singkat dan jelas.",
        tone="prompt",
    )

def _build_contact_request_success_answer(selected: dict, action_result: dict[str, Any]) -> str:
    detail = str(action_result.get("detail") or "").strip()
    if detail:
        return detail

    action_type = str(action_result.get("type") or "").strip().lower()
    if action_type in {"call", "start_two_way_call"}:
        return (
            f"Saya sedang mencoba menyambungkan Anda dengan {selected['nama']}. "
            "Mohon izinkan akses mikrofon bila diminta."
        )

    return (
        f"Permintaan kontak untuk {selected['nama']} sudah diterima. "
        "Silakan lanjutkan instruksi berikutnya."
    )

def _is_unavailable_contact_status(status: str) -> bool:
    return status in {"busy", "unavailable", "offline", "not_available", "no_response", "failed"}

def _is_successful_contact_status(status: str) -> bool:
    return status in {"preparing", "dialing_employee", "queued", "ringing", "connected", "accepted", "sent"}

def _build_contact_response(
    *,
    answer: str,
    conversation_id: str | None,
    flow_state: dict[str, Any] | None = None,
    action_result: dict[str, Any] | None = None,
    follow_up: dict[str, Any] | None = None,
) -> dict:
    safe_flow_state = flow_state if isinstance(flow_state, dict) else {"stage": "idle"}
    normalized_answer = " ".join((answer or "").split()).strip()

    payload: dict[str, Any] = {
        "handled": True,
        "answer": normalized_answer,
        "flow_state": safe_flow_state,
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if action_result:
        payload["action"] = action_result
    if follow_up:
        payload["follow_up"] = follow_up
    return payload

def _default_contact_delivery_detail(status: str) -> str:
    normalized_status = str(status or "").strip().lower()
    if normalized_status == "sent":
        return "Pesan sudah terkirim."
    if normalized_status in {"accepted", "queued"}:
        return "Pesan sudah diterima sistem dan sedang diproses."
    return "Pesan belum berhasil dikirim."

def _build_notify_delivery_answer(employee_name: str, delivery_status: str) -> str:
    normalized_status = str(delivery_status or "").strip().lower()
    if normalized_status == "sent":
        return f"Baik, pesan Anda untuk {employee_name} sudah terkirim. Mohon tunggu beberapa saat."
    if normalized_status in {"accepted", "queued"}:
        return f"Baik, pesan Anda untuk {employee_name} sudah diterima sistem dan sedang diproses. Mohon tunggu beberapa saat."
    return "Maaf, pesan belum bisa terkirim. Silakan coba lagi beberapa saat."


def _expired_response(conversation_id: str | None, flow_context: dict, msg: str) -> dict:
    """Kembalikan response 'sesi berakhir' dan reset ke idle."""
    store_chat_message(conversation_id, "assistant", msg)
    return _build_contact_response(
        answer=msg,
        conversation_id=conversation_id,
        flow_state=_build_stage("idle", flow_context),
    )
