"""Database dialect helpers shared by local and server persistence paths."""

from __future__ import annotations

from sqlalchemy.engine import Connection


def begin_write_transaction(connection: Connection) -> None:
    """Take SQLite's early writer reservation; other engines already have a txn."""

    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")
