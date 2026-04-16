import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

from config import settings


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class AdminRepository:
    @staticmethod
    def _configure_connection(connection: sqlite3.Connection) -> sqlite3.Connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _connect() -> sqlite3.Connection:
        connection = sqlite3.connect(settings.chat_db_path, timeout=5)
        return AdminRepository._configure_connection(connection)

    @staticmethod
    def _create_contact_messages_table(connection: sqlite3.Connection, table_name: str = "contact_messages") -> None:
        connection.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                employee_nama TEXT NOT NULL,
                employee_departemen TEXT NOT NULL,
                employee_nomor_wa TEXT NOT NULL,
                visitor_name TEXT NOT NULL,
                visitor_goal TEXT NOT NULL,
                message_text TEXT NOT NULL,
                channel TEXT NOT NULL,
                delivery_status TEXT NOT NULL,
                delivery_detail TEXT NOT NULL,
                delivery_provider TEXT NOT NULL DEFAULT 'dummy',
                provider_message_id TEXT,
                provider_payload TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                sent_at TEXT
            );
            """
        )

    @staticmethod
    def _create_contact_messages_indexes(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_contact_messages_employee_id
            ON contact_messages(employee_id);

            CREATE INDEX IF NOT EXISTS idx_contact_messages_created_at
            ON contact_messages(created_at DESC);
            """
        )

    @staticmethod
    def _migrate_contact_messages_without_fk(connection: sqlite3.Connection) -> None:
        AdminRepository._create_contact_messages_table(connection, table_name="contact_messages_migrated")
        connection.execute(
            """
            INSERT INTO contact_messages_migrated (
                id,
                employee_id,
                employee_nama,
                employee_departemen,
                employee_nomor_wa,
                visitor_name,
                visitor_goal,
                message_text,
                channel,
                delivery_status,
                delivery_detail,
                created_at,
                updated_at,
                sent_at
            )
            SELECT
                id,
                employee_id,
                employee_nama,
                employee_departemen,
                employee_nomor_wa,
                visitor_name,
                visitor_goal,
                message_text,
                channel,
                delivery_status,
                delivery_detail,
                created_at,
                updated_at,
                sent_at
            FROM contact_messages
            """
        )
        connection.execute("DROP TABLE contact_messages")
        connection.execute("ALTER TABLE contact_messages_migrated RENAME TO contact_messages")

    @staticmethod
    def _ensure_contact_messages_columns(connection: sqlite3.Connection) -> None:
        rows = connection.execute("PRAGMA table_info(contact_messages)").fetchall()
        existing_columns = {str(row["name"]) for row in rows}

        required_columns = {
            "delivery_provider": "TEXT NOT NULL DEFAULT 'dummy'",
            "provider_message_id": "TEXT",
            "provider_payload": "TEXT",
        }

        for column_name, column_definition in required_columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(
                f"ALTER TABLE contact_messages ADD COLUMN {column_name} {column_definition}"
            )

    @staticmethod
    def _row_to_contact_message(row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None

        return {
            "id": row["id"],
            "employee_id": row["employee_id"],
            "employee_nama": row["employee_nama"],
            "employee_departemen": row["employee_departemen"],
            "employee_nomor_wa": row["employee_nomor_wa"],
            "visitor_name": row["visitor_name"],
            "visitor_goal": row["visitor_goal"],
            "message_text": row["message_text"],
            "channel": row["channel"],
            "delivery_status": row["delivery_status"],
            "delivery_detail": row["delivery_detail"],
            "delivery_provider": row["delivery_provider"],
            "provider_message_id": row["provider_message_id"],
            "provider_payload": row["provider_payload"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "sent_at": row["sent_at"],
        }

    @staticmethod
    def _fetch_contact_message(connection: sqlite3.Connection, message_id: int) -> dict | None:
        row = connection.execute(
            """
            SELECT
                id,
                employee_id,
                employee_nama,
                employee_departemen,
                employee_nomor_wa,
                visitor_name,
                visitor_goal,
                message_text,
                channel,
                delivery_status,
                delivery_detail,
                delivery_provider,
                provider_message_id,
                provider_payload,
                created_at,
                updated_at,
                sent_at
            FROM contact_messages
            WHERE id = ?
            """,
            (message_id,),
        ).fetchone()
        return AdminRepository._row_to_contact_message(row)

    @staticmethod
    def initialize() -> None:
        settings.chat_db_path.parent.mkdir(parents=True, exist_ok=True)
        if not settings.chat_db_path.exists():
            settings.chat_db_path.write_bytes(b"")

        with closing(AdminRepository._connect()) as connection, connection:
            contact_messages_table = connection.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = 'contact_messages'
                """
            ).fetchone()

            if not contact_messages_table:
                AdminRepository._create_contact_messages_table(connection)
            else:
                foreign_keys = connection.execute("PRAGMA foreign_key_list(contact_messages)").fetchall()
                if foreign_keys:
                    AdminRepository._migrate_contact_messages_without_fk(connection)

            AdminRepository._ensure_contact_messages_columns(connection)
            AdminRepository._create_contact_messages_indexes(connection)
            connection.execute("DROP TABLE IF EXISTS employees")

    @staticmethod
    def create_contact_message(
        *,
        employee_id: int,
        employee_nama: str,
        employee_departemen: str,
        employee_nomor_wa: str,
        visitor_name: str,
        visitor_goal: str,
        message_text: str,
        channel: str,
        delivery_status: str,
        delivery_detail: str,
        delivery_provider: str = "dummy",
        provider_message_id: str | None = None,
        provider_payload: dict[str, Any] | list[Any] | str | None = None,
    ) -> dict:
        timestamp = _utc_now_iso()
        provider_payload_text: str | None
        if isinstance(provider_payload, (dict, list)):
            provider_payload_text = json.dumps(provider_payload, ensure_ascii=False)
        elif provider_payload is None:
            provider_payload_text = None
        else:
            provider_payload_text = str(provider_payload)

        with closing(AdminRepository._connect()) as connection, connection:
            cursor = connection.execute(
                """
                INSERT INTO contact_messages (
                    employee_id,
                    employee_nama,
                    employee_departemen,
                    employee_nomor_wa,
                    visitor_name,
                    visitor_goal,
                    message_text,
                    channel,
                    delivery_status,
                    delivery_detail,
                    delivery_provider,
                    provider_message_id,
                    provider_payload,
                    created_at,
                    updated_at,
                    sent_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    employee_id,
                    employee_nama,
                    employee_departemen,
                    employee_nomor_wa,
                    visitor_name,
                    visitor_goal,
                    message_text,
                    channel,
                    delivery_status,
                    delivery_detail,
                    delivery_provider,
                    provider_message_id,
                    provider_payload_text,
                    timestamp,
                    timestamp,
                    None,
                ),
            )
            message_id = cursor.lastrowid
            stored = AdminRepository._fetch_contact_message(connection, int(message_id))

        return stored or {}

    @staticmethod
    def update_contact_message_delivery(
        *,
        message_id: int,
        delivery_status: str,
        delivery_detail: str,
        delivery_provider: str,
        provider_message_id: str | None = None,
        provider_payload: dict[str, Any] | list[Any] | str | None = None,
        mark_sent: bool = False,
    ) -> dict | None:
        timestamp = _utc_now_iso()
        provider_payload_text: str | None
        if isinstance(provider_payload, (dict, list)):
            provider_payload_text = json.dumps(provider_payload, ensure_ascii=False)
        elif provider_payload is None:
            provider_payload_text = None
        else:
            provider_payload_text = str(provider_payload)

        with closing(AdminRepository._connect()) as connection, connection:
            if mark_sent:
                connection.execute(
                    """
                    UPDATE contact_messages
                    SET delivery_status = ?,
                        delivery_detail = ?,
                        delivery_provider = ?,
                        provider_message_id = ?,
                        provider_payload = ?,
                        updated_at = ?,
                        sent_at = ?
                    WHERE id = ?
                    """,
                    (
                        delivery_status,
                        delivery_detail,
                        delivery_provider,
                        provider_message_id,
                        provider_payload_text,
                        timestamp,
                        timestamp,
                        message_id,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE contact_messages
                    SET delivery_status = ?,
                        delivery_detail = ?,
                        delivery_provider = ?,
                        provider_message_id = ?,
                        provider_payload = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        delivery_status,
                        delivery_detail,
                        delivery_provider,
                        provider_message_id,
                        provider_payload_text,
                        timestamp,
                        message_id,
                    ),
                )

            return AdminRepository._fetch_contact_message(connection, message_id)

    @staticmethod
    def mark_contact_message_sent_dummy(*, message_id: int, delivery_detail: str) -> dict | None:
        return AdminRepository.update_contact_message_delivery(
            message_id=message_id,
            delivery_status="sent_dummy",
            delivery_detail=delivery_detail,
            delivery_provider="dummy",
            provider_message_id="",
            provider_payload={"mode": "dummy"},
            mark_sent=True,
        )

    @staticmethod
    def list_contact_messages(limit: int = 50) -> list[dict]:
        safe_limit = max(1, min(int(limit or 50), 200))
        with closing(AdminRepository._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    employee_id,
                    employee_nama,
                    employee_departemen,
                    employee_nomor_wa,
                    visitor_name,
                    visitor_goal,
                    message_text,
                    channel,
                    delivery_status,
                    delivery_detail,
                    delivery_provider,
                    provider_message_id,
                    provider_payload,
                    created_at,
                    updated_at,
                    sent_at
                FROM contact_messages
                ORDER BY id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()

        return [AdminRepository._row_to_contact_message(row) for row in rows if row]
