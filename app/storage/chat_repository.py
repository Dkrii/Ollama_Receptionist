import logging
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from contextlib import closing

from config import settings


_logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _conversation_expiry(now: datetime | None = None) -> str:
    started_at = now or _utc_now()
    expires_at = started_at + timedelta(minutes=settings.chat_session_idle_minutes)
    return _utc_iso(expires_at)


class ChatRepository:
    _available = True

    @staticmethod
    def _configure_connection(connection: sqlite3.Connection) -> sqlite3.Connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _connect() -> sqlite3.Connection:
        if not ChatRepository._available:
            raise RuntimeError("Chat repository is unavailable")

        connection = sqlite3.connect(settings.chat_db_path, timeout=5)
        return ChatRepository._configure_connection(connection)

    @staticmethod
    def initialize() -> None:
        try:
            settings.chat_db_path.parent.mkdir(parents=True, exist_ok=True)
            if not settings.chat_db_path.exists():
                settings.chat_db_path.write_bytes(b"")
        except Exception as e:
            ChatRepository._available = False
            _logger.exception("chat.sqlite.file_creation_failed error=%s path=%s", e, settings.chat_db_path)
            return

        try:
            with closing(ChatRepository._connect()) as connection, connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS conversations (
                        id TEXT PRIMARY KEY,
                        visitor_key TEXT NULL,
                        created_at TEXT NOT NULL,
                        last_activity_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
                    ON messages(conversation_id, created_at);

                    CREATE INDEX IF NOT EXISTS idx_conversations_last_activity
                    ON conversations(last_activity_at);

                    CREATE INDEX IF NOT EXISTS idx_conversations_expires_at
                    ON conversations(expires_at);
                    """
                )
                connection.execute("SELECT 1")
        except Exception:
            ChatRepository._available = False
            _logger.exception("chat.sqlite.unavailable path=%s", settings.chat_db_path)
            return

        ChatRepository._available = True
        _logger.info("chat.sqlite.ready path=%s", settings.chat_db_path.resolve())

    @staticmethod
    def cleanup_expired_transcripts() -> None:
        cutoff = _utc_iso(_utc_now() - timedelta(days=settings.chat_transcript_retention_days))
        with closing(ChatRepository._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM conversations WHERE last_activity_at < ?",
                (cutoff,),
            )

    @staticmethod
    def create_conversation(visitor_key: str | None = None) -> str:
        ChatRepository.cleanup_expired_transcripts()

        conversation_id = str(uuid.uuid4())
        now = _utc_now()
        timestamp = _utc_iso(now)

        with closing(ChatRepository._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO conversations (id, visitor_key, created_at, last_activity_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    visitor_key,
                    timestamp,
                    timestamp,
                    _conversation_expiry(now),
                ),
            )

        return conversation_id

    @staticmethod
    def resolve_conversation(conversation_id: str | None) -> str:
        if not conversation_id:
            return ChatRepository.create_conversation()

        row = ChatRepository.get_conversation(conversation_id)
        if not row:
            return ChatRepository.create_conversation()

        if row["expires_at"] <= _utc_iso(_utc_now()):
            return ChatRepository.create_conversation()

        return conversation_id

    @staticmethod
    def get_conversation(conversation_id: str) -> sqlite3.Row | None:
        with closing(ChatRepository._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT id, visitor_key, created_at, last_activity_at, expires_at
                FROM conversations
                WHERE id = ?
                """,
                (conversation_id,),
            ).fetchone()
        return row

    @staticmethod
    def get_recent_turns(conversation_id: str, limit: int | None = None) -> list[dict]:
        capped_limit = max(1, limit or settings.chat_recent_turns)

        with closing(ChatRepository._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT role, content, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (conversation_id, capped_limit),
            ).fetchall()

        return [
            {
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
            for row in reversed(rows)
        ]

    @staticmethod
    def add_message(conversation_id: str, role: str, content: str) -> None:
        text = (content or "").strip()
        if not text:
            return

        now = _utc_now()
        timestamp = _utc_iso(now)
        expires_at = _conversation_expiry(now)

        with closing(ChatRepository._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO messages (conversation_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, role, text, timestamp),
            )
            connection.execute(
                """
                UPDATE conversations
                SET last_activity_at = ?, expires_at = ?
                WHERE id = ?
                """,
                (timestamp, expires_at, conversation_id),
            )
