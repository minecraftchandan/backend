"""PostgreSQL connection adapter and lifecycle management."""

import os
import re
from contextlib import contextmanager
from threading import Lock
from typing import Any, Iterator

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from app.db.schema import DDL, MIGRATIONS
from app.db.seed import apply_seed

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
_initialization_lock = Lock()
_initialized = False


class PostgresConnection:
    """Small adapter for the existing parameterized SQL used by the demo services."""

    def __init__(self, connection: psycopg.Connection):
        self._connection = connection

    @staticmethod
    def _translate(query: str) -> str:
        translated = re.sub(
            r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
            "INSERT INTO",
            query,
            flags=re.IGNORECASE,
        )
        ignored_conflicts = translated != query
        translated = translated.replace("?", "%s")
        translated = re.sub(r"(?<!:):([A-Za-z_]\w*)", r"%(\1)s", translated)
        if ignored_conflicts:
            translated = translated.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        return translated

    def execute(self, query: str, params: Any = None):
        return self._connection.execute(self._translate(query), params)

    def executemany(self, query: str, params_seq):
        cursor = self._connection.cursor()
        cursor.executemany(self._translate(query), params_seq)
        return cursor

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


def _initialize_connection(connection: PostgresConnection) -> None:
    global _initialized
    if _initialized:
        return

    with _initialization_lock:
        if _initialized:
            return

        connection.executescript(DDL)
        connection.executescript(MIGRATIONS)
        apply_seed(connection)
        connection.commit()
        _initialized = True


@contextmanager
def get_connection() -> Iterator[PostgresConnection]:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL must be set to a PostgreSQL connection URL.")
    connection = PostgresConnection(
        psycopg.connect(DATABASE_URL, connect_timeout=10, row_factory=dict_row)
    )
    try:
        _initialize_connection(connection)
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with get_connection():
        pass
