from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


_logger = logging.getLogger(__name__)

_ALIAS_PATTERN = re.compile(r"[^A-Za-z0-9]+")
_READ_QUERY_PREFIX_PATTERN = re.compile(r"^\s*(?:SELECT|WITH)\b", re.IGNORECASE)
_WRITE_KEYWORD_PATTERN = re.compile(
    r"\b(?:ALTER|CALL|CREATE|DELETE|DROP|EXEC|EXECUTE|GRANT|INSERT|MERGE|REPLACE|REVOKE|TRUNCATE|UPDATE)\b",
    re.IGNORECASE,
)
_PRIMARY_ALIAS = "postgres"


class DatabaseConfigurationError(RuntimeError):
    pass


class DatabaseDriverError(RuntimeError):
    pass


class DatabaseQueryError(RuntimeError):
    pass


QueryParams = Mapping[str, Any] | Sequence[Any]


@dataclass(frozen=True)
class DatabaseConnectionConfig:
    alias: str
    driver: str
    host: str
    port: int
    name: str
    user: str
    password: str
    timeout_seconds: int


def _normalize_alias(alias: str | None) -> str:
    normalized = _ALIAS_PATTERN.sub("_", str(alias or _PRIMARY_ALIAS).strip()).strip("_").lower()
    if normalized.startswith("db_"):
        normalized = normalized[3:]
    return normalized or _PRIMARY_ALIAS


def _env_key(alias: str, name: str) -> str:
    return f"DB_{_normalize_alias(alias).upper()}_{name}"


def _env(alias: str, name: str, fallback: str = "") -> str:
    return os.getenv(_env_key(alias, name), fallback).strip()


def _normalize_driver(value: str) -> str:
    driver = str(value or "").strip().lower()
    if driver in {"postgres", "postgresql", "pg"}:
        return "postgres"
    if driver in {"mssql", "sqlserver", "sql_server"}:
        return "mssql"
    if not driver:
        return ""
    raise DatabaseConfigurationError(f"Unsupported database driver: {driver}")


def _default_port(driver: str) -> int:
    if driver == "postgres":
        return 5432
    if driver == "mssql":
        return 1433
    return 0


def _parse_int(value: str, fallback: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except Exception:
        return fallback
    return parsed if parsed > 0 else fallback


def get_connection_config(alias: str = _PRIMARY_ALIAS) -> DatabaseConnectionConfig:
    normalized_alias = _normalize_alias(alias)
    driver = _normalize_driver(_env(normalized_alias, "DRIVER"))
    host = _env(normalized_alias, "HOST")
    name = _env(normalized_alias, "NAME")

    missing = []
    if not driver:
        missing.append(_env_key(normalized_alias, "DRIVER"))
    if not host:
        missing.append(_env_key(normalized_alias, "HOST"))
    if not name:
        missing.append(_env_key(normalized_alias, "NAME"))
    if missing:
        raise DatabaseConfigurationError(
            f"Database connection '{normalized_alias}' is incomplete: {', '.join(missing)}"
        )

    port = _parse_int(_env(normalized_alias, "PORT"), _default_port(driver))
    timeout_seconds = _parse_int(_env(normalized_alias, "TIMEOUT_SECONDS"), 10)

    return DatabaseConnectionConfig(
        alias=normalized_alias,
        driver=driver,
        host=host,
        port=port,
        name=name,
        user=_env(normalized_alias, "USER"),
        password=_env(normalized_alias, "PASSWORD"),
        timeout_seconds=timeout_seconds,
    )


def _connect_postgres(config: DatabaseConnectionConfig):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise DatabaseDriverError("psycopg is not installed") from exc

    return psycopg.connect(
        host=config.host,
        port=config.port,
        dbname=config.name,
        user=config.user or None,
        password=config.password or None,
        connect_timeout=config.timeout_seconds,
        row_factory=dict_row,
    )


def _connect_mssql(config: DatabaseConnectionConfig):
    try:
        import pymssql
    except ImportError as exc:
        raise DatabaseDriverError("pymssql is not installed") from exc

    return pymssql.connect(
        server=config.host,
        user=config.user,
        password=config.password,
        database=config.name,
        port=config.port,
        timeout=config.timeout_seconds,
        login_timeout=config.timeout_seconds,
        as_dict=True,
    )


def get_connection(alias: str = _PRIMARY_ALIAS):
    config = get_connection_config(alias)
    if config.driver == "postgres":
        return _connect_postgres(config)
    if config.driver == "mssql":
        return _connect_mssql(config)
    raise DatabaseConfigurationError(f"Unsupported database driver: {config.driver}")


def _close_quietly(resource: Any) -> None:
    close = getattr(resource, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:
        _logger.debug("database resource close failed", exc_info=True)


def _row_to_dict(row: Any, cursor: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "items"):
        return dict(row.items())

    description = getattr(cursor, "description", None) or []
    columns = [column[0] for column in description]
    return {column: value for column, value in zip(columns, row)}


def _assert_read_only_query(query: str) -> None:
    sql = str(query or "").strip()
    if not sql:
        raise DatabaseQueryError("Database fetch query is empty")
    if not _READ_QUERY_PREFIX_PATTERN.search(sql):
        raise DatabaseQueryError("Database fetch helpers only allow SELECT queries")
    if _WRITE_KEYWORD_PATTERN.search(sql):
        raise DatabaseQueryError("Database fetch helpers cannot run write statements")


def fetch_all(query: str, params: QueryParams | None = None, *, alias: str = _PRIMARY_ALIAS) -> list[dict[str, Any]]:
    _assert_read_only_query(query)
    connection = get_connection(alias)
    cursor = None
    try:
        cursor = connection.cursor()
        if params is None:
            cursor.execute(query)
        else:
            cursor.execute(query, params)
        rows = cursor.fetchall() or []
        return [_row_to_dict(row, cursor) for row in rows]
    finally:
        _close_quietly(cursor)
        _close_quietly(connection)


def fetch_one(query: str, params: QueryParams | None = None, *, alias: str = _PRIMARY_ALIAS) -> dict[str, Any] | None:
    _assert_read_only_query(query)
    connection = get_connection(alias)
    cursor = None
    try:
        cursor = connection.cursor()
        if params is None:
            cursor.execute(query)
        else:
            cursor.execute(query, params)
        row = cursor.fetchone()
        return _row_to_dict(row, cursor) if row is not None else None
    finally:
        _close_quietly(cursor)
        _close_quietly(connection)
