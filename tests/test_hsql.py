"""hsql against the shipped adapter and the live ClickHouse.

These are the commands an agent runs. They shell out to ``hsql``; they do not
reimplement it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

NATIVE = "clickhouse://clickhouse:clickhouse@127.0.0.1:9004/sample_db"
HTTP = "clickhouse://clickhouse:clickhouse@127.0.0.1:8123/sample_db"
HSQL = Path(sys.executable).with_name("hsql")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(HSQL), "-P", "None", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _jsonl(stdout: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def test_info_declares_read_only_and_cancel() -> None:
    completed = _run("--info", "-a", "clickhouse")
    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    clickhouse = document["adapters"]["clickhouse"]
    assert clickhouse["error"] is None
    capabilities = clickhouse["capabilities"]
    assert capabilities["implements_read_only"] is True
    assert capabilities["implements_cancel"] is True
    assert capabilities["implements_catalog_search"] is False


def test_help_lists_connection_options_twice() -> None:
    first = _run("--help", "-a", "clickhouse")
    second = _run("--help", "-a", "clickhouse")
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout
    for word in ("host", "port", "user", "password", "database", "secure", "setting"):
        assert word in first.stdout
    assert "TLS" in first.stdout


def test_catalog_levels_and_clickhouse_types() -> None:
    databases = _run(
        "-a",
        "clickhouse",
        HTTP,
        "--catalog",
        "--jsonl",
        "--no-write-history",
    )
    assert databases.returncode == 0, databases.stderr
    database_rows = _jsonl(databases.stdout)
    assert any(row["name"] == "sample_db" for row in database_rows)

    relations = _run(
        "-a",
        "clickhouse",
        HTTP,
        "--catalog",
        "--path",
        "sample_db",
        "--jsonl",
        "--no-write-history",
    )
    assert relations.returncode == 0, relations.stderr
    relation_rows = _jsonl(relations.stdout)
    by_name = {str(row["name"]): row for row in relation_rows}
    for name in ("customers", "orders", "types_demo", "v_orders_summary"):
        assert name in by_name
    assert "`customers`" in str(by_name["customers"]["query_name"])

    columns = _run(
        "-a",
        "clickhouse",
        NATIVE,
        "--catalog",
        "--path",
        "sample_db.types_demo",
        "--jsonl",
        "--no-write-history",
    )
    assert columns.returncode == 0, columns.stderr
    rendered = columns.stdout
    for token in ("Array", "Map", "Tuple", "Decimal", "DateTime64", "Nullable"):
        assert token in rendered


def test_schema_shaped_path_and_catalog_search_exit_2() -> None:
    missing = _run(
        "-a",
        "clickhouse",
        HTTP,
        "--catalog",
        "--path",
        "sample_db.not_a_schema.customers",
        "--no-write-history",
    )
    assert missing.returncode == 2
    search = _run(
        "-a",
        "clickhouse",
        HTTP,
        "--catalog-search",
        "customers",
        "--no-write-history",
    )
    assert search.returncode == 2
    assert "catalog" in search.stderr.lower()


def test_both_urls_and_limit() -> None:
    for url in (HTTP, NATIVE):
        completed = _run(
            "-a",
            "clickhouse",
            url,
            "--no-write-history",
            "--limit",
            "-1",
            "-tAc",
            "SELECT currentDatabase()",
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == "sample_db"

    limited = _run(
        "-a",
        "clickhouse",
        HTTP,
        "--no-write-history",
        "--limit",
        "1",
        "-tA",
        "-c",
        "SELECT customer_id FROM customers ORDER BY customer_id",
    )
    assert limited.returncode == 0, limited.stderr
    lines = [line for line in limited.stdout.splitlines() if line.strip()]
    assert len(lines) == 1


def test_read_only_blocks_ddl_and_bad_sql_exits_1() -> None:
    name = f"hq_hsql_{uuid4().hex[:12]}"
    blocked = _run(
        "-a",
        "clickhouse",
        HTTP,
        "-r",
        "--no-write-history",
        "-c",
        (f"CREATE TABLE {name} (id UInt32) ENGINE = MergeTree ORDER BY id"),
    )
    assert blocked.returncode == 1, blocked.stderr

    readable = _run(
        "-a",
        "clickhouse",
        HTTP,
        "-r",
        "--no-write-history",
        "-tAc",
        "SELECT currentDatabase()",
    )
    assert readable.returncode == 0, readable.stderr
    assert readable.stdout.strip() == "sample_db"

    rejected = _run(
        "-a",
        "clickhouse",
        NATIVE,
        "--no-write-history",
        "-c",
        "SELECT * FROM sample_db.no_such_table_zzz",
    )
    assert rejected.returncode == 1


def test_bad_password_exits_3() -> None:
    completed = _run(
        "-a",
        "clickhouse",
        "clickhouse://clickhouse:wrong-password@127.0.0.1:8123/sample_db",
        "--no-write-history",
        "-c",
        "SELECT 1",
    )
    assert completed.returncode == 3
    assert "AttributeError" not in completed.stderr
    assert (
        "conn" not in completed.stderr
        or "could not connect" in completed.stderr.lower()
    )
