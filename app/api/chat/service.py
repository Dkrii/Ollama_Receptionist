from shared.services.chat_service import ChatService


class ChatAppService:
    @staticmethod
    def ask(message: str, history: list[dict] | None = None) -> dict:
        return ChatService.ask(message, history=history)

    @staticmethod
    def ask_stream(message: str, history: list[dict] | None = None):
        return ChatService.ask_stream(message, history=history)
