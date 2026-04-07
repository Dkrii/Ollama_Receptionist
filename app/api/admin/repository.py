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
