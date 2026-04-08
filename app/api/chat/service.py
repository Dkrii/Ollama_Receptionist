import json
import logging
import re
import time
from typing import Any

from api.admin.repository import AdminRepository
from api.chat.repository import ChatRepository
from config import settings
from rag.generate import generate_answer, generate_answer_stream
from rag.retrieve import retrieve_context

_logger = logging.getLogger(__name__)
CHAT_SYSTEM_FALLBACK = "Maaf, sistem sedang mengalami gangguan. Silakan coba lagi sebentar."
EMPLOYEE_QUERY_MARKERS = (
    "karyawan",
    "pegawai",
    "staff",
    "staf",
    "nama karyawan",
    "daftar karyawan",
    "employee",
)
CONTACT_INTENT_MARKERS = (
    "hubungi",
    "sambungkan",
    "telepon",
    "telpon",
    "call",
    "kontak",
    "panggil",
)
MEET_INTENT_MARKERS = (
    "ketemu",
    "bertemu",
    "temui",
    "menemui",
    "jumpa",
)
CONTACT_TARGET_MARKERS = (
    "karyawan",
    "pegawai",
    "staff",
    "staf",
    "orang",
)
CONFUSED_MARKERS = (
    "bagian komputer",
    "bagian it",
    "yang it",
    "yang bagian",
    "hmm",
    "emm",
)
LEAVE_MESSAGE_MARKERS = (
    "tinggalkan pesan",
    "pesan saja",
    "kirim pesan",
    "titip pesan",
)
WAIT_MARKERS = (
    "saya tunggu",
    "menunggu",
    "di lobby",
    "di lobi",
    "temui saya",
)
SYSTEM_CONTACT_TIMEOUT_TOKEN = "__contact_timeout__"
CONFIRM_YES_MARKERS = (
    "ya",
    "iya",
    "yes",
    "betul",
    "benar",
    "ok",
    "oke",
    "lanjut",
)
CONFIRM_NO_MARKERS = (
    "tidak",
    "bukan",
    "no",
    "cancel",
    "batal",
)


def _trim_history(history: list[dict] | None) -> list[dict]:
    if not history:
        return []

    trimmed_history: list[dict] = []
    for item in history[-settings.chat_recent_turns:]:
        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()
        if not role or not content:
            continue
        trimmed_history.append({"role": role, "content": content})
    return trimmed_history


def _resolve_chat_memory(conversation_id: str | None, history: list[dict] | None = None) -> tuple[str | None, list[dict], bool]:
    fallback_history = _trim_history(history)
    try:
        resolved_conversation_id = ChatRepository.resolve_conversation(conversation_id)
        prior_history = ChatRepository.get_recent_turns(resolved_conversation_id)
        if not prior_history and not conversation_id:
            prior_history = fallback_history
        return resolved_conversation_id, prior_history, True
    except Exception:
        _logger.exception("chat.memory unavailable conversation_id=%s", conversation_id)
        return None, fallback_history, False


def _store_chat_message(conversation_id: str | None, role: str, content: str) -> None:
    if not conversation_id:
        return
    try:
        ChatRepository.add_message(conversation_id, role, content)
    except Exception:
        _logger.exception("chat.memory write failed conversation_id=%s role=%s", conversation_id, role)


def _build_answer_payload(answer: str, citations: list[dict], conversation_id: str | None) -> dict:
    payload = {
        "answer": answer,
        "citations": citations,
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    return payload


def _is_employee_query(message: str) -> bool:
    lowered = " ".join((message or "").lower().split())
    return any(marker in lowered for marker in EMPLOYEE_QUERY_MARKERS)


def _build_employee_context() -> tuple[str, list[dict]]:
    try:
        employees = AdminRepository.list_employees()
    except Exception:
        _logger.exception("chat.employee_context failed to load employees")
        return "", []

    if not employees:
        return "", []

    lines = [
        f"- {employee['nama']} | Departemen: {employee['departemen']} | Jabatan: {employee['jabatan']} | WA: {employee['nomor_wa']}"
        for employee in employees
    ]
    context = "DATA KARYAWAN TERDAFTAR:\n" + "\n".join(lines)
    citation = {
        "content": context,
        "metadata": {
            "source": "employees",
            "path": "sqlite:employees",
            "chunk_index": 0,
        },
        "score": 1.0,
    }
    return context, [citation]


def _build_employee_answer() -> tuple[str, list[dict]]:
    employee_context, employee_citations = _build_employee_context()
    if not employee_context:
        return "Data karyawan belum tersedia saat ini.", []

    try:
        employees = AdminRepository.list_employees()
    except Exception:
        _logger.exception("chat.employee_answer failed to load employees")
        return "Data karyawan belum tersedia saat ini.", []

    if not employees:
        return "Data karyawan belum tersedia saat ini.", []

    employees = sorted(employees, key=lambda item: str(item.get("nama", "")).lower())

    max_visible_items = 6
    visible_employees = employees[:max_visible_items]

    lines = ["Berikut daftar karyawan yang terdaftar:"]
    for idx, employee in enumerate(visible_employees, start=1):
        lines.append(
            f"{idx}. {employee['nama']} — {employee['departemen']}, {employee['jabatan']}"
        )

    remaining_count = len(employees) - len(visible_employees)
    if remaining_count > 0:
        lines.append(f"dan {remaining_count} karyawan lainnya.")

    lines.append("Sebutkan nama karyawan jika ingin detail kontak WA.")

    return "\n".join(lines), employee_citations


def _build_retrieval_result(message: str, history: list[dict]) -> tuple[dict, float]:
    retrieval_started_at = time.perf_counter()
    try:
        retrieval = retrieve_context(message, history=history)
    except Exception:
        _logger.exception("chat.retrieve failed message=%s", message)
        retrieval = {"context": "", "citations": []}

    if _is_employee_query(message):
        employee_context, employee_citations = _build_employee_context()
        if employee_context:
            base_context = (retrieval.get("context") or "").strip()
            retrieval["context"] = f"{base_context}\n\n{employee_context}".strip() if base_context else employee_context
            retrieval["citations"] = [*employee_citations, *(retrieval.get("citations") or [])]

    retrieval_ms = (time.perf_counter() - retrieval_started_at) * 1000
    return retrieval, retrieval_ms


def _normalize_text(value: str) -> str:
    return " ".join((value or "").lower().split())


def _is_contact_intent(message: str) -> bool:
    normalized = _normalize_text(message)
    if not normalized:
        return False

    has_action = any(marker in normalized for marker in CONTACT_INTENT_MARKERS)
    has_meet = any(marker in normalized for marker in MEET_INTENT_MARKERS)
    has_target = any(marker in normalized for marker in CONTACT_TARGET_MARKERS)
    has_from_division = " dari " in f" {normalized} "

    cleaned = normalized
    for marker in CONTACT_INTENT_MARKERS:
        cleaned = re.sub(rf"\b{re.escape(marker)}\b", " ", cleaned)
    for marker in ("tolong", "saya", "mau", "ingin", "dong"):
        cleaned = re.sub(rf"\b{re.escape(marker)}\b", " ", cleaned)
    residual_tokens = [token for token in re.sub(r"[^a-z0-9\s]", " ", cleaned).split() if token]
    has_direct_subject = has_action and len(residual_tokens) >= 1

    return (has_action and has_target) or has_meet or (has_action and has_from_division) or has_direct_subject


def _is_confused_contact_request(message: str) -> bool:
    normalized = _normalize_text(message)
    if not normalized:
        return False
    return any(marker in normalized for marker in CONFUSED_MARKERS)


def _is_confirmation_yes(message: str) -> bool:
    normalized = _normalize_text(message)
    if not normalized:
        return False
    tokens = set(re.sub(r"[^a-z0-9\s]", " ", normalized).split())
    return bool(tokens.intersection(CONFIRM_YES_MARKERS))


def _is_confirmation_no(message: str) -> bool:
    normalized = _normalize_text(message)
    if not normalized:
        return False
    tokens = set(re.sub(r"[^a-z0-9\s]", " ", normalized).split())
    return bool(tokens.intersection(CONFIRM_NO_MARKERS))


def _detect_contact_action(message: str, flow_state: dict[str, Any] | None = None) -> str:
    normalized = _normalize_text(message)
    if any(marker in normalized for marker in ("call", "telepon", "telpon")):
        return "call"
    if any(marker in normalized for marker in ("notifikasi", "notif", "pesan", "wa", "whatsapp")):
        return "notify"
    if isinstance(flow_state, dict):
        saved = str(flow_state.get("action") or "").strip().lower()
        if saved in {"call", "notify"}:
            return saved
    return "notify"


def _is_leave_message_request(message: str) -> bool:
    normalized = _normalize_text(message)
    if not normalized:
        return False
    return any(marker in normalized for marker in LEAVE_MESSAGE_MARKERS)


def _is_waiting_response(message: str) -> bool:
    normalized = _normalize_text(message)
    if not normalized:
        return False
    return any(marker in normalized for marker in WAIT_MARKERS)


def _employee_matches_query(employee: dict, query: str) -> bool:
    normalized_query = _normalize_text(query)
    if not normalized_query:
        return True

    tokens = [token for token in re.sub(r"[^a-z0-9\s]", " ", normalized_query).split() if token]
    if not tokens:
        return True

    employee_blob = _normalize_text(
        " ".join(
            [
                str(employee.get("nama", "")),
                str(employee.get("departemen", "")),
                str(employee.get("jabatan", "")),
            ]
        )
    )

    return all(token in employee_blob for token in tokens)


def _search_employees(query: str) -> list[dict]:
    try:
        employees = AdminRepository.list_employees()
    except Exception:
        _logger.exception("chat.contact search failed")
        return []

    matches = [employee for employee in employees if _employee_matches_query(employee, query)]
    matches.sort(key=lambda item: str(item.get("nama", "")).lower())
    return matches


def _extract_employee_query(message: str) -> str:
    normalized = _normalize_text(message)
    cleaned = normalized
    stop_phrases = (
        "tolong",
        "mau",
        "ingin",
        "saya",
        "bisa",
        "dong",
        "menghubungi",
        "mengontak",
        "mengontakki",
        "mengkontak",
        "menghubunginya",
        "ketemu",
        "bertemu",
        "temui",
        "menemui",
        "jumpa",
        "pak",
        "bu",
        "dari",
        "divisi",
        "bagian",
        "hubungi",
        "sambungkan",
        "telepon",
        "telpon",
        "call",
        "kontak",
        "panggil",
        "karyawan",
        "pegawai",
        "staff",
        "staf",
    )
    for phrase in stop_phrases:
        cleaned = re.sub(rf"\b{re.escape(phrase)}\b", " ", cleaned)

    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or normalized


def _extract_employee_name_lookup_query(message: str) -> str:
    normalized = _normalize_text(message)
    if not normalized:
        return ""

    has_name_token = " nama " in f" {normalized} "
    if not has_name_token:
        return ""

    lookup_markers = (
        "apakah",
        "ada",
        "terdaftar",
        "di sini",
        "disini",
        "di perusahaan",
        "di kantor",
        "karyawan",
        "pegawai",
        "staff",
        "staf",
    )
    if not any(marker in normalized for marker in lookup_markers):
        return ""

    cleaned = normalized
    stop_phrases = (
        "apakah",
        "ada",
        "nama",
        "yang",
        "bernama",
        "di",
        "sini",
        "disini",
        "kantor",
        "perusahaan",
        "ini",
        "karyawan",
        "pegawai",
        "staff",
        "staf",
    )
    for phrase in stop_phrases:
        cleaned = re.sub(rf"\b{re.escape(phrase)}\b", " ", cleaned)

    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _build_employee_name_lookup_answer(query: str) -> tuple[str, list[dict]]:
    matches = _search_employees(query)
    _, citations = _build_employee_context()

    if not matches:
        return f"Saya belum menemukan nama {query.title()} di data karyawan saat ini.", citations

    visible_matches = matches[:3]
    match_details = ", ".join(_format_employee_brief(employee) for employee in visible_matches)
    remaining_count = len(matches) - len(visible_matches)

    answer = f"Ya, saya menemukan {len(matches)} data yang cocok untuk nama {query.title()}: {match_details}."
    if remaining_count > 0:
        answer += f" Dan {remaining_count} data lainnya."

    answer += " Jika ingin, saya bisa bantu hubungi salah satunya."
    return answer, citations


def _format_employee_brief(employee: dict) -> str:
    return f"{employee['nama']} ({employee['departemen']} - {employee['jabatan']})"


def _format_employee_for_prompt(employee: dict) -> str:
    return f"{employee['nama']} dari {employee['departemen']}"


def _extract_person_name_input(message: str) -> str:
    value = (message or "").strip()
    if not value:
        return ""

    head = value.split(",", 1)[0].strip()
    normalized_head = _normalize_text(head)
    normalized_head = re.sub(r"[^a-z0-9\s]", " ", normalized_head)
    raw_tokens = [token for token in normalized_head.split() if token]
    if not raw_tokens:
        return ""

    filler_words = {
        "nama",
        "saya",
        "adalah",
        "dari",
        "pak",
        "bu",
        "mbak",
        "mas",
        "tujuan",
        "keperluan",
        "meeting",
        "vendor",
        "hubungi",
        "kontak",
    }
    tokens = [token for token in raw_tokens if token not in filler_words]
    if not tokens:
        return ""

    return " ".join(word.capitalize() for word in tokens[:3])


def _extract_visitor_goal_input(message: str) -> str:
    value = (message or "").strip()
    if not value:
        return ""

    lowered = _normalize_text(value)
    markers = ("tujuan", "keperluan", "perlu", "untuk")
    for marker in markers:
        key = f"{marker}"
        idx = lowered.find(key)
        if idx >= 0:
            goal_text = value[idx + len(marker):].strip(" :,-")
            if goal_text:
                return goal_text

    if "," in value:
        tail = value.split(",", 1)[1].strip()
        if tail:
            return tail

    return value


def _create_dummy_contact_message(selected: dict, message_content: str) -> tuple[bool, dict | None]:
    visitor_name = _extract_person_name_input(message_content)
    visitor_goal = _extract_visitor_goal_input(message_content)

    if not visitor_name or len(visitor_goal) < 5:
        return False, None

    stored = AdminRepository.create_contact_message(
        employee_id=int(selected["id"]),
        employee_nama=str(selected["nama"]),
        employee_departemen=str(selected["departemen"]),
        employee_nomor_wa=str(selected["nomor_wa"]),
        visitor_name=visitor_name,
        visitor_goal=visitor_goal,
        message_text=message_content,
        channel="whatsapp",
        delivery_status="queued_dummy",
        delivery_detail="Menunggu dummy dispatcher",
    )
    delivered = AdminRepository.mark_contact_message_sent_dummy(
        message_id=int(stored["id"]),
        delivery_detail="Dummy WhatsApp dispatcher berhasil (simulasi tanpa API key)",
    )
    return True, delivered


def _build_contact_response(
    *,
    answer: str,
    conversation_id: str | None,
    flow_state: dict[str, Any] | None = None,
    action_result: dict[str, Any] | None = None,
    follow_up: dict[str, Any] | None = None,
) -> dict:
    payload: dict[str, Any] = {
        "handled": True,
        "answer": answer,
        "flow_state": flow_state or {"stage": "idle"},
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if action_result:
        payload["action"] = action_result
    if follow_up:
        payload["follow_up"] = follow_up
    return payload


def _resolve_disambiguation_choice(message: str, candidates: list[dict]) -> dict | None:
    stripped = _normalize_text(message)
    if not stripped:
        return None

    number_match = re.search(r"\b(\d{1,2})\b", stripped)
    if number_match:
        idx = int(number_match.group(1)) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx]

    for employee in candidates:
        name = _normalize_text(str(employee.get("nama", "")))
        department = _normalize_text(str(employee.get("departemen", "")))
        if name and name in stripped:
            return employee
        if department and department in stripped:
            return employee

    return None


def _perform_contact_action(employee: dict, action: str) -> dict[str, Any]:
    if action == "call":
        return {
            "type": "call",
            "status": "queued",
            "employee": {
                "id": employee["id"],
                "nama": employee["nama"],
                "departemen": employee["departemen"],
                "jabatan": employee["jabatan"],
            },
            "detail": "Permintaan panggilan (VoIP/WebRTC) diterima.",
        }

    return {
        "type": "notify",
        "status": "queued",
        "employee": {
            "id": employee["id"],
            "nama": employee["nama"],
            "departemen": employee["departemen"],
            "jabatan": employee["jabatan"],
            "nomor_wa": employee["nomor_wa"],
        },
        "detail": "Notifikasi diteruskan ke karyawan.",
    }


class ChatAppService:
    @staticmethod
    def handle_contact_flow(
        message: str,
        conversation_id: str | None = None,
        history: list[dict] | None = None,
        flow_state: dict[str, Any] | None = None,
    ) -> dict:
        resolved_conversation_id, _, _ = _resolve_chat_memory(conversation_id, history=history)
        user_message = (message or "").strip()
        safe_flow_state = flow_state if isinstance(flow_state, dict) else {}
        stage = str(safe_flow_state.get("stage") or "idle").strip().lower()
        action = _detect_contact_action(user_message, safe_flow_state)

        if not user_message:
            return {
                "handled": False,
                "flow_state": {"stage": "idle"},
                "conversation_id": resolved_conversation_id,
            }

        is_active_stage = stage in {
            "await_disambiguation",
            "await_confirmation",
            "contacting_unavailable_pending",
            "await_unavailable_choice",
            "await_waiter_name",
            "await_message_content",
        }
        if not is_active_stage and not _is_contact_intent(user_message):
            if _is_confused_contact_request(user_message):
                answer = "Anda bisa mengatakan: hubungi nama dari divisi. Contoh: hubungi Budi dari IT."
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={"stage": "idle"},
                )
            return {
                "handled": False,
                "flow_state": {"stage": "idle"},
                "conversation_id": resolved_conversation_id,
            }

        is_internal_timeout_event = (
            stage == "contacting_unavailable_pending"
            and _normalize_text(user_message) == SYSTEM_CONTACT_TIMEOUT_TOKEN
        )
        if not is_internal_timeout_event:
            _store_chat_message(resolved_conversation_id, "user", user_message)

        if stage == "await_disambiguation":
            candidates = safe_flow_state.get("candidates") or []
            if not isinstance(candidates, list) or not candidates:
                answer = "Pilihan kandidat sudah kedaluwarsa. Silakan sebutkan lagi siapa karyawan yang ingin dihubungi."
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={"stage": "idle"},
                )

            selected = _resolve_disambiguation_choice(user_message, candidates)
            if not selected:
                option_names = [item["nama"] for item in candidates[:3] if item.get("nama")]
                answer = "Saya menemukan beberapa karyawan bernama serupa."
                if len(option_names) == 1:
                    answer += f" Apakah {option_names[0]}?"
                elif len(option_names) == 2:
                    answer += f" Apakah {option_names[0]} atau {option_names[1]}?"
                elif len(option_names) >= 3:
                    answer += f" Apakah {option_names[0]}, {option_names[1]}, atau {option_names[2]}?"
                else:
                    answer += " Silakan sebutkan nama lengkap karyawan yang ingin dihubungi."
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={
                        "stage": "await_disambiguation",
                        "action": action,
                        "candidates": candidates,
                    },
                )

            answer = f"Apakah Anda ingin menghubungi {_format_employee_for_prompt(selected)}?"
            _store_chat_message(resolved_conversation_id, "assistant", answer)
            return _build_contact_response(
                answer=answer,
                conversation_id=resolved_conversation_id,
                flow_state={
                    "stage": "await_confirmation",
                    "action": action,
                    "selected": selected,
                },
            )

        if stage == "contacting_unavailable_pending":
            selected = safe_flow_state.get("selected") or {}
            if not isinstance(selected, dict) or not selected.get("id"):
                answer = "Sesi panggilan berakhir. Silakan ulangi permintaan hubungi karyawan."
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={"stage": "idle"},
                )

            timeout_triggered = _normalize_text(user_message) == SYSTEM_CONTACT_TIMEOUT_TOKEN
            if timeout_triggered:
                answer = (
                    f"{selected['nama']} sedang tidak tersedia. "
                    "Silakan tinggalkan pesan dengan menyebutkan nama dan tujuan, "
                    "lalu menuju lobby untuk menunggu."
                )
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={
                        "stage": "await_unavailable_choice",
                        "action": action,
                        "selected": selected,
                    },
                )

            stage = "await_unavailable_choice"

        if stage == "await_confirmation":
            selected = safe_flow_state.get("selected") or {}
            if not isinstance(selected, dict) or not selected.get("id"):
                answer = "Sesi konfirmasi sudah berakhir. Silakan ulangi permintaan hubungi karyawan."
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={"stage": "idle"},
                )

            if _is_confirmation_no(user_message):
                answer = "Baik, saya batalkan. Silakan sebutkan lagi nama karyawan yang ingin dihubungi."
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={"stage": "idle"},
                )

            if not _is_confirmation_yes(user_message):
                answer = "Mohon jawab dengan ya atau tidak untuk konfirmasi."
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={
                        "stage": "await_confirmation",
                        "action": action,
                        "selected": selected,
                    },
                )

            action_result = _perform_contact_action(selected, action)
            answer = (
                f"Baik, saya sedang menghubungi {selected['nama']}. "
                "Silakan tunggu sekitar 10 detik."
            )

            _store_chat_message(resolved_conversation_id, "assistant", answer)
            return _build_contact_response(
                answer=answer,
                conversation_id=resolved_conversation_id,
                flow_state={
                    "stage": "contacting_unavailable_pending",
                    "action": action,
                    "selected": selected,
                },
                action_result=action_result,
                follow_up={
                    "mode": "timeout-check",
                    "after_ms_min": 10000,
                    "after_ms_max": 10000,
                    "message": SYSTEM_CONTACT_TIMEOUT_TOKEN,
                },
            )

        if stage == "await_unavailable_choice":
            selected = safe_flow_state.get("selected") or {}
            if not isinstance(selected, dict) or not selected.get("id"):
                answer = "Sesi tidak tersedia berakhir. Silakan ulangi permintaan hubungi karyawan."
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={"stage": "idle"},
                )

            if _is_leave_message_request(user_message):
                answer = "Silakan sampaikan pesan Anda dengan menyebutkan nama dan tujuan."
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={
                        "stage": "await_message_content",
                        "action": action,
                        "selected": selected,
                    },
                )

            if _is_waiting_response(user_message):
                answer = (
                    f"Baik, silakan sebutkan nama Anda. "
                    f"Saya akan menyampaikan kepada {selected['nama']} bahwa Anda menunggu di lobby."
                )
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={
                        "stage": "await_waiter_name",
                        "action": action,
                        "selected": selected,
                    },
                )

            answer = (
                "Anda bisa bilang: tinggalkan pesan saja, "
                "lalu menuju lobby untuk menunggu."
            )
            _store_chat_message(resolved_conversation_id, "assistant", answer)
            return _build_contact_response(
                answer=answer,
                conversation_id=resolved_conversation_id,
                flow_state={
                    "stage": "await_unavailable_choice",
                    "action": action,
                    "selected": selected,
                },
            )

        if stage == "await_waiter_name":
            selected = safe_flow_state.get("selected") or {}
            if not isinstance(selected, dict) or not selected.get("id"):
                answer = "Sesi menunggu berakhir. Silakan ulangi permintaan hubungi karyawan."
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={"stage": "idle"},
                )

            visitor_name = _extract_person_name_input(user_message)
            if not visitor_name:
                answer = "Silakan sebutkan nama Anda terlebih dahulu."
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={
                        "stage": "await_waiter_name",
                        "action": action,
                        "selected": selected,
                    },
                )

            answer = (
                f"Baik, {visitor_name}. Saya akan menyampaikan kepada {selected['nama']} "
                "bahwa Anda menunggu di lobby."
            )
            _store_chat_message(resolved_conversation_id, "assistant", answer)
            return _build_contact_response(
                answer=answer,
                conversation_id=resolved_conversation_id,
                flow_state={"stage": "idle"},
            )

        if stage == "await_message_content":
            selected = safe_flow_state.get("selected") or {}
            if not isinstance(selected, dict) or not selected.get("id"):
                answer = "Sesi pesan berakhir. Silakan ulangi permintaan hubungi karyawan."
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={"stage": "idle"},
                )

            message_content = user_message.strip()
            if len(message_content) < 3:
                answer = "Pesannya terlalu singkat. Silakan sampaikan pesan Anda sekali lagi."
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={
                        "stage": "await_message_content",
                        "action": action,
                        "selected": selected,
                    },
                )

            is_valid_payload, delivered_payload = _create_dummy_contact_message(selected, message_content)
            if not is_valid_payload:
                answer = "Mohon sebutkan pesan dengan format nama dan tujuan. Contoh: Saya Andi, tujuan meeting vendor."
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={
                        "stage": "await_message_content",
                        "action": action,
                        "selected": selected,
                    },
                )

            answer = (
                f"Baik, pesan Anda sudah saya catat untuk {selected['nama']} "
                "dan berhasil diproses lewat dummy dispatcher. "
                "Saat ini notifikasi WhatsApp real belum aktif, silakan menunggu di lobby."
            )
            _store_chat_message(resolved_conversation_id, "assistant", answer)
            return _build_contact_response(
                answer=answer,
                conversation_id=resolved_conversation_id,
                flow_state={"stage": "idle"},
                action_result={
                    "type": "notify",
                    "status": "sent_dummy",
                    "employee": {
                        "id": selected["id"],
                        "nama": selected["nama"],
                        "departemen": selected["departemen"],
                        "jabatan": selected["jabatan"],
                    },
                    "message": delivered_payload,
                },
            )

        search_query = _extract_employee_query(user_message)
        matches = _search_employees(search_query)

        if not matches:
            if _is_confused_contact_request(user_message):
                answer = "Anda bisa mengatakan: hubungi nama dari divisi. Contoh: hubungi Budi dari IT."
                _store_chat_message(resolved_conversation_id, "assistant", answer)
                return _build_contact_response(
                    answer=answer,
                    conversation_id=resolved_conversation_id,
                    flow_state={"stage": "idle"},
                )

            answer = "Saya tidak menemukan karyawan tersebut. Silakan sebutkan nama lengkap atau divisinya."
            _store_chat_message(resolved_conversation_id, "assistant", answer)
            return _build_contact_response(
                answer=answer,
                conversation_id=resolved_conversation_id,
                flow_state={"stage": "idle"},
            )

        if len(matches) == 1:
            selected = matches[0]
            answer = f"Apakah Anda ingin menghubungi {_format_employee_for_prompt(selected)}?"
            _store_chat_message(resolved_conversation_id, "assistant", answer)
            return _build_contact_response(
                answer=answer,
                conversation_id=resolved_conversation_id,
                flow_state={
                    "stage": "await_confirmation",
                    "action": action,
                    "selected": selected,
                },
            )

        candidates = matches[:5]
        option_names = [item["nama"] for item in candidates[:3] if item.get("nama")]
        answer = "Saya menemukan beberapa karyawan bernama serupa."
        if option_names:
            if len(option_names) == 1:
                answer += f" Apakah {option_names[0]}?"
            elif len(option_names) == 2:
                answer += f" Apakah {option_names[0]} atau {option_names[1]}?"
            else:
                answer += f" Apakah {option_names[0]}, {option_names[1]}, atau {option_names[2]}?"
        _store_chat_message(resolved_conversation_id, "assistant", answer)
        return _build_contact_response(
            answer=answer,
            conversation_id=resolved_conversation_id,
            flow_state={
                "stage": "await_disambiguation",
                "action": action,
                "candidates": candidates,
            },
        )

    @staticmethod
    def ask(message: str, conversation_id: str | None = None, history: list[dict] | None = None) -> dict:
        started_at = time.perf_counter()
        resolved_conversation_id, prior_history, _ = _resolve_chat_memory(conversation_id, history=history)
        try:
            _store_chat_message(resolved_conversation_id, "user", message)

            employee_name_lookup_query = _extract_employee_name_lookup_query(message)
            if employee_name_lookup_query:
                lookup_answer, lookup_citations = _build_employee_name_lookup_answer(employee_name_lookup_query)
                _store_chat_message(resolved_conversation_id, "assistant", lookup_answer)
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                _logger.info(
                    "chat.ask route=employee_name_lookup conversation_id=%s total_ms=%.1f query=%s",
                    resolved_conversation_id,
                    elapsed_ms,
                    employee_name_lookup_query,
                )
                return _build_answer_payload(lookup_answer, lookup_citations, resolved_conversation_id)

            if _is_employee_query(message):
                employee_answer, employee_citations = _build_employee_answer()
                _store_chat_message(resolved_conversation_id, "assistant", employee_answer)
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                _logger.info(
                    "chat.ask route=employee_data conversation_id=%s total_ms=%.1f",
                    resolved_conversation_id,
                    elapsed_ms,
                )
                return _build_answer_payload(employee_answer, employee_citations, resolved_conversation_id)

            retrieval, retrieval_ms = _build_retrieval_result(message, prior_history)

            # fallback_answer = _fallback_answer_from_retrieval(message, retrieval)
            # if fallback_answer:
            #     _store_chat_message(resolved_conversation_id, "assistant", fallback_answer)
            #     return _build_answer_payload(fallback_answer, retrieval["citations"], resolved_conversation_id)

            answer_started_at = time.perf_counter()
            answer = generate_answer(message, retrieval["context"], history=prior_history)
            answer_ms = (time.perf_counter() - answer_started_at) * 1000
            _store_chat_message(resolved_conversation_id, "assistant", answer)

            elapsed_ms = (time.perf_counter() - started_at) * 1000
            _logger.info(
                "chat.ask route=rag conversation_id=%s retrieval_ms=%.1f answer_ms=%.1f total_ms=%.1f",
                resolved_conversation_id,
                retrieval_ms,
                answer_ms,
                elapsed_ms,
            )
            return _build_answer_payload(answer, retrieval["citations"], resolved_conversation_id)
        except Exception:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            _logger.exception(
                "chat.ask route=rag failed conversation_id=%s total_ms=%.1f",
                resolved_conversation_id,
                elapsed_ms,
            )
            return _build_answer_payload(CHAT_SYSTEM_FALLBACK, [], resolved_conversation_id)

    @staticmethod
    def ask_stream(message: str, conversation_id: str | None = None, history: list[dict] | None = None):
        started_at = time.perf_counter()
        resolved_conversation_id, prior_history, _ = _resolve_chat_memory(conversation_id, history=history)

        _store_chat_message(resolved_conversation_id, "user", message)

        employee_name_lookup_query = _extract_employee_name_lookup_query(message)
        if employee_name_lookup_query:
            lookup_answer, lookup_citations = _build_employee_name_lookup_answer(employee_name_lookup_query)

            def _employee_lookup_events():
                meta_payload = {"type": "meta"}
                if resolved_conversation_id:
                    meta_payload["conversation_id"] = resolved_conversation_id
                yield json.dumps(meta_payload, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "token", "value": lookup_answer}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "citations", "value": lookup_citations}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
                _store_chat_message(resolved_conversation_id, "assistant", lookup_answer)

            return _employee_lookup_events()

        if _is_employee_query(message):
            employee_answer, employee_citations = _build_employee_answer()

            def _employee_events():
                meta_payload = {"type": "meta"}
                if resolved_conversation_id:
                    meta_payload["conversation_id"] = resolved_conversation_id
                yield json.dumps(meta_payload, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "token", "value": employee_answer}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "citations", "value": employee_citations}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
                _store_chat_message(resolved_conversation_id, "assistant", employee_answer)

            return _employee_events()

        retrieval, retrieval_ms = _build_retrieval_result(message, prior_history)

        def _events():
            collected_tokens: list[str] = []
            try:
                meta_payload = {"type": "meta"}
                if resolved_conversation_id:
                    meta_payload["conversation_id"] = resolved_conversation_id
                yield json.dumps(meta_payload, ensure_ascii=False) + "\n"

                # fallback_answer = _fallback_answer_from_retrieval(message, retrieval)
                # if fallback_answer:
                #     _store_chat_message(resolved_conversation_id, "assistant", fallback_answer)
                #     yield json.dumps({"type": "token", "value": fallback_answer}, ensure_ascii=False) + "\n"
                #     yield json.dumps({"type": "citations", "value": retrieval["citations"]}, ensure_ascii=False) + "\n"
                #     yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
                #     return

                first_token_logged = False
                for token in generate_answer_stream(message, retrieval["context"], history=prior_history):
                    if not first_token_logged and token:
                        first_token_ms = (time.perf_counter() - started_at) * 1000
                        _logger.info(
                            "chat.stream route=rag conversation_id=%s retrieval_ms=%.1f first_token_ms=%.1f",
                            resolved_conversation_id,
                            retrieval_ms,
                            first_token_ms,
                        )
                        first_token_logged = True
                    if token:
                        collected_tokens.append(token)
                    yield json.dumps({"type": "token", "value": token}, ensure_ascii=False) + "\n"
                final_answer = "".join(collected_tokens).strip()
                if final_answer:
                    _store_chat_message(resolved_conversation_id, "assistant", final_answer)
                yield json.dumps({"type": "citations", "value": retrieval["citations"]}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
            except Exception:
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                _logger.exception(
                    "chat.stream route=rag failed conversation_id=%s retrieval_ms=%.1f total_ms=%.1f",
                    resolved_conversation_id,
                    retrieval_ms,
                    elapsed_ms,
                )
                yield json.dumps(
                    {"type": "error", "value": CHAT_SYSTEM_FALLBACK},
                    ensure_ascii=False,
                ) + "\n"

        return _events()
