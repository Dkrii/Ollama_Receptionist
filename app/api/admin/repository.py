import sqlite3
from contextlib import closing
from datetime import datetime, timezone

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
    def initialize() -> None:
        settings.chat_db_path.parent.mkdir(parents=True, exist_ok=True)
        if not settings.chat_db_path.exists():
            settings.chat_db_path.write_bytes(b"")

        with closing(AdminRepository._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS employees (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama TEXT NOT NULL,
                    departemen TEXT NOT NULL,
                    jabatan TEXT NOT NULL,
                    nomor_wa TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_employees_nama
                ON employees(nama);

                CREATE TABLE IF NOT EXISTS contact_messages (
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
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    sent_at TEXT,
                    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_contact_messages_employee_id
                ON contact_messages(employee_id);

                CREATE INDEX IF NOT EXISTS idx_contact_messages_created_at
                ON contact_messages(created_at DESC);
                """
            )

    @staticmethod
    def create_employee(*, nama: str, departemen: str, jabatan: str, nomor_wa: str) -> dict:
        timestamp = _utc_now_iso()
        with closing(AdminRepository._connect()) as connection, connection:
            cursor = connection.execute(
                """
                INSERT INTO employees (nama, departemen, jabatan, nomor_wa, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (nama, departemen, jabatan, nomor_wa, timestamp),
            )
            employee_id = cursor.lastrowid

            row = connection.execute(
                """
                SELECT id, nama, departemen, jabatan, nomor_wa, created_at
                FROM employees
                WHERE id = ?
                """,
                (employee_id,),
            ).fetchone()

        return {
            "id": row["id"],
            "nama": row["nama"],
            "departemen": row["departemen"],
            "jabatan": row["jabatan"],
            "nomor_wa": row["nomor_wa"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def list_employees() -> list[dict]:
        with closing(AdminRepository._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT id, nama, departemen, jabatan, nomor_wa, created_at
                FROM employees
                ORDER BY id DESC
                """
            ).fetchall()

        return [
            {
                "id": row["id"],
                "nama": row["nama"],
                "departemen": row["departemen"],
                "jabatan": row["jabatan"],
                "nomor_wa": row["nomor_wa"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

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
    ) -> dict:
        timestamp = _utc_now_iso()
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
                    created_at,
                    updated_at,
                    sent_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    timestamp,
                    timestamp,
                    None,
                ),
            )
            message_id = cursor.lastrowid

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
                    created_at,
                    updated_at,
                    sent_at
                FROM contact_messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()

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
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "sent_at": row["sent_at"],
        }

    @staticmethod
    def mark_contact_message_sent_dummy(*, message_id: int, delivery_detail: str) -> dict | None:
        timestamp = _utc_now_iso()
        with closing(AdminRepository._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE contact_messages
                SET delivery_status = ?,
                    delivery_detail = ?,
                    updated_at = ?,
                    sent_at = ?
                WHERE id = ?
                """,
                ("sent_dummy", delivery_detail, timestamp, timestamp, message_id),
            )

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
                    created_at,
                    updated_at,
                    sent_at
                FROM contact_messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()

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
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "sent_at": row["sent_at"],
        }

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
                    created_at,
                    updated_at,
                    sent_at
                FROM contact_messages
                ORDER BY id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()

        return [
            {
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
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "sent_at": row["sent_at"],
            }
            for row in rows
        ]
