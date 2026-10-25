"""Live tests against the homenetwork ClickHouse. They do not mock the driver."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from uuid import uuid4

import pytest
from harlequin.exception import HarlequinConnectionError, HarlequinQueryError

from harlequin_clickhouse import ClickHouseAdapter, ClickHouseConnection

NATIVE = "clickhouse://clickhouse:clickhouse@127.0.0.1:9004/sample_db"
HTTP = "clickhouse://clickhouse:clickhouse@127.0.0.1:8123/sample_db"
URLS = (NATIVE, HTTP)
TYPE_TOKENS = ("Array", "Map", "Tuple", "Decimal", "DateTime64", "Nullable")
RELATIONS = ("customers", "orders", "types_demo", "v_orders_summary")


@pytest.fixture(params=URLS)
def conn(request: pytest.FixtureRequest) -> Iterator[ClickHouseConnection]:
    connection = ClickHouseAdapter([request.param]).connect()
    try:
        yield connection
    finally:
        connection.close()


def test_sample_db_query_and_conn_attribute(conn: ClickHouseConnection) -> None:
    assert conn.conn is not None
    catalog = conn.get_catalog()
    assert catalog.items
    cursor = conn.execute("SELECT currentDatabase()")
    assert cursor is not None
    rows = cursor.fetchall()
    assert rows is not None
    assert rows[0][0] == "sample_db"
    counted = conn.execute("SELECT count() FROM customers")
    assert counted is not None
    count_rows = counted.fetchall()
    assert count_rows is not None
    assert int(count_rows[0][0]) >= 1


def test_catalog_lists_seed_relations_and_clickhouse_types(
    conn: ClickHouseConnection,
) -> None:
    relations = {
        item.label: item
        for database in conn.get_catalog().items
        if database.label == "sample_db"
        for item in database.children
    }
    for name in RELATIONS:
        assert name in relations
    assert relations["v_orders_summary"].type_label == "v"
    labels = " ".join(column.type_label for column in relations["types_demo"].children)
    for token in TYPE_TOKENS:
        assert token in labels


def test_row_limit_bounds_the_fetch(conn: ClickHouseConnection) -> None:
    cursor = conn.execute("SELECT customer_id FROM customers ORDER BY customer_id")
    assert cursor is not None
    cursor.set_limit(1)
    rows = cursor.fetchall()
    assert rows is not None
    assert len(rows) == 1


def test_ddl_round_trip(conn: ClickHouseConnection) -> None:
    name = f"hq_scratch_{uuid4().hex[:12]}"
    try:
        created = conn.execute(
            f"CREATE TABLE {name} (id UInt32, label String) "
            "ENGINE = MergeTree ORDER BY id"
        )
        assert created is None
        inserted = conn.execute(f"INSERT INTO {name} VALUES (1, 'roundtrip')")
        assert inserted is None
        cursor = conn.execute(f"SELECT label FROM {name}")
        assert cursor is not None
        rows = cursor.fetchall()
        assert rows is not None
        assert rows[0][0] == "roundtrip"
    finally:
        conn.execute(f"DROP TABLE IF EXISTS {name}")


def test_rejected_query(conn: ClickHouseConnection) -> None:
    cursor = conn.execute("SELECT * FROM sample_db.no_such_table_zzz")
    assert cursor is not None
    with pytest.raises(HarlequinQueryError):
        cursor.fetchall()


def test_completions_are_real_clickhouse_tokens(conn: ClickHouseConnection) -> None:
    completions = conn.get_completions()
    labels = {item.label for item in completions}
    values = {item.value for item in completions}
    tokens = labels | values
    assert "foo" not in tokens
    assert "bar" not in tokens
    assert "baz" not in tokens
    assert "ARRAY JOIN" in tokens
    assert "arrayJoin" in tokens
    assert "toDateTime64" in tokens


def test_cancel_then_select_one(conn: ClickHouseConnection) -> None:
    assert ClickHouseAdapter.IMPLEMENTS_CANCEL is True
    conn.cancel()
    cursor = conn.execute("SELECT 1")
    assert cursor is not None
    rows = cursor.fetchall()
    assert rows is not None
    assert int(rows[0][0]) == 1


@pytest.mark.parametrize("url", URLS)
def test_cancel_aborts_inflight_query(url: str) -> None:
    """cancel() must kill a statement that is actually running, including HTTP."""
    connection = ClickHouseAdapter([url]).connect()
    watcher = ClickHouseAdapter([url]).connect()
    worker: threading.Thread | None = None
    try:
        cursor = connection.execute("SELECT sleep(3)")
        assert cursor is not None
        caught: list[BaseException] = []
        done = threading.Event()

        def run() -> None:
            try:
                cursor.fetchall()
            except BaseException as exc:
                caught.append(exc)
            finally:
                done.set()

        started = time.monotonic()
        worker = threading.Thread(target=run)
        worker.start()
        visible = False
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            query_id = connection._current_query_id
            if query_id and query_id.isalnum():
                seen = watcher.execute(
                    "SELECT count() FROM system.processes "
                    f"WHERE query_id = '{query_id}'"
                )
                assert seen is not None
                found = seen.fetchall()
                assert found is not None
                if int(found[0][0]) >= 1:
                    visible = True
                    break
            time.sleep(0.05)
        assert visible, "the sleep query never reached ClickHouse"
        connection.cancel()
        assert done.wait(timeout=2.0)
        elapsed = time.monotonic() - started
        assert caught, "sleep ran to completion; cancel did not abort it"
        assert isinstance(caught[0], HarlequinQueryError)
        assert "394" in str(caught[0])
        assert elapsed < 2.5
        follow = connection.execute("SELECT 1")
        assert follow is not None
        rows = follow.fetchall()
        assert rows is not None
        assert int(rows[0][0]) == 1
    finally:
        if worker is not None:
            worker.join(timeout=5)
        connection.close()
        watcher.close()


def test_read_only_constructor_and_select() -> None:
    adapter = ClickHouseAdapter(
        [HTTP],
        read_only=True,
        not_a_real_option="ignored",
    )
    connection = adapter.connect()
    try:
        assert connection.conn is not None
        cursor = connection.execute("SELECT currentDatabase()")
        assert cursor is not None
        rows = cursor.fetchall()
        assert rows is not None
        assert rows[0][0] == "sample_db"
    finally:
        connection.close()


def test_bad_password_raises_connection_error() -> None:
    adapter = ClickHouseAdapter(
        ["clickhouse://clickhouse:wrong-password@127.0.0.1:8123/sample_db"]
    )
    with pytest.raises(HarlequinConnectionError):
        adapter.connect()


def test_entry_point_loads_the_shipped_adapter() -> None:
    from importlib.metadata import entry_points

    matches = [
        item
        for item in entry_points(group="harlequin.adapter")
        if item.name == "clickhouse"
    ]
    assert matches
    loaded = matches[-1].load()
    assert loaded is ClickHouseAdapter
