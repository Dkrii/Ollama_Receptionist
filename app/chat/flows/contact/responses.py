from typing import Any


def follow_up_prompt(stage: str, *, eyebrow: str, title: str, message: str, tone: str = "prompt") -> dict[str, Any]:
    return {
        "type": "prompt",
        "stage": stage,
        "eyebrow": eyebrow,
        "title": title,
        "message": message,
        "tone": tone,
    }


def cancelled_answer() -> str:
    return "Baik, saya batalkan dulu. Ada hal lain yang bisa saya bantu?"
