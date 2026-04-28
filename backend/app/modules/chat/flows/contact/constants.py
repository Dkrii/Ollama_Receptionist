IDLE = "idle"
AWAIT_DISAMBIGUATION = "await_disambiguation"
AWAIT_CONFIRMATION = "await_confirmation"
AWAIT_UNAVAILABLE_CHOICE = "await_unavailable_choice"
AWAIT_MESSAGE_NAME = "await_message_name"
AWAIT_MESSAGE_GOAL = "await_message_goal"
AWAIT_MESSAGE_CONFIRMATION = "await_message_confirmation"

ACTIVE_STAGES = {
    AWAIT_DISAMBIGUATION,
    AWAIT_CONFIRMATION,
    AWAIT_UNAVAILABLE_CHOICE,
    AWAIT_MESSAGE_NAME,
    AWAIT_MESSAGE_GOAL,
    AWAIT_MESSAGE_CONFIRMATION,
}


def idle_state(context: dict | None = None) -> dict:
    return {
        "stage": IDLE,
        "context": context or {
            "last_topic_type": "none",
            "last_topic_value": "",
            "last_intent": "unknown",
        },
    }
