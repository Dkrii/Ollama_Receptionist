from shared.services.chat_service import ChatService


class ChatAppService:
    @staticmethod
    def ask(message: str) -> dict:
        return ChatService.ask(message)

    @staticmethod
    def ask_stream(message: str):
        return ChatService.ask_stream(message)
