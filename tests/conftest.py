"""Seed a ClickHouse database for the live tests.

The session creates its own database and drops it afterwards, unless that
database already existed. Live tests skip when no server answers. See
``tests/server.py`` for the environment variables.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from .server import DATABASE, HOST, HTTP_PORT, PASSWORD, SEED, USER


def _client() -> Any:
    import clickhouse_connect

    return clickhouse_connect.get_client(
        host=HOST, port=HTTP_PORT, username=USER, password=PASSWORD
    )


@pytest.fixture(scope="session")
def clickhouse_db() -> Iterator[str]:
    """Seed the test database once per session."""
    try:
        client = _client()
    except Exception as exc:  # noqa: BLE001 - any failure means no server
        pytest.skip(f"No ClickHouse server at {HOST}:{HTTP_PORT}: {exc}")
    existed = bool(
        client.command(
            "SELECT count() FROM system.databases WHERE name = {db:String}",
            parameters={"db": DATABASE},
        )
    )
    if not existed:
        client.command(f"CREATE DATABASE `{DATABASE}`")
        for statement in SEED:
            client.command(statement.format(db=f"`{DATABASE}`"))
    try:
        yield DATABASE
    finally:
        if not existed:
            client.command(f"DROP DATABASE IF EXISTS `{DATABASE}`")
        client.close()
