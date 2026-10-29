"""Where the live tests find ClickHouse.

Set these environment variables to point the tests at a server. The defaults
match a stock ``clickhouse/clickhouse-server`` container on this machine::

    CLICKHOUSE_HOST=127.0.0.1
    CLICKHOUSE_HTTP_PORT=8123
    CLICKHOUSE_NATIVE_PORT=9000
    CLICKHOUSE_USER=default
    CLICKHOUSE_PASSWORD=
    CLICKHOUSE_TEST_DATABASE=harlequin_test
"""

from __future__ import annotations

import os
from urllib.parse import quote

HOST = os.environ.get("CLICKHOUSE_HOST", "127.0.0.1")
HTTP_PORT = int(os.environ.get("CLICKHOUSE_HTTP_PORT", "8123"))
NATIVE_PORT = int(os.environ.get("CLICKHOUSE_NATIVE_PORT", "9000"))
USER = os.environ.get("CLICKHOUSE_USER", "default")
PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "")
DATABASE = os.environ.get("CLICKHOUSE_TEST_DATABASE", "harlequin_test")


def url(interface: str, *, password: str = PASSWORD) -> str:
    """A connection URL for the test server. The interface is explicit."""
    port = HTTP_PORT if interface == "http" else NATIVE_PORT
    auth = quote(USER, safe="")
    if password:
        auth += ":" + quote(password, safe="")
    return f"clickhouse://{auth}@{HOST}:{port}/{DATABASE}?interface={interface}"


NATIVE = url("native")
HTTP = url("http")
WRONG_PASSWORD = url("http", password=PASSWORD + "-wrong")

SEED = (
    "CREATE TABLE {db}.customers (customer_id UInt32, name String) "
    "ENGINE = MergeTree ORDER BY customer_id",
    "CREATE TABLE {db}.orders (order_id UInt32, customer_id UInt32, "
    "amount Decimal(12, 2), ordered_at DateTime64(3)) "
    "ENGINE = MergeTree ORDER BY order_id",
    "CREATE TABLE {db}.types_demo (id UInt32, tags Array(String), "
    "attrs Map(String, UInt32), pair Tuple(UInt8, String), "
    "price Decimal(10, 2), seen_at DateTime64(3), note Nullable(String), "
    "uid UUID) ENGINE = MergeTree ORDER BY id",
    "CREATE VIEW {db}.v_orders_summary AS SELECT customer_id, "
    "count() AS orders, sum(amount) AS total FROM {db}.orders "
    "GROUP BY customer_id",
    "INSERT INTO {db}.customers VALUES (1, 'Ada'), (2, 'Grace'), (3, 'Edsger')",
    "INSERT INTO {db}.orders VALUES (1, 1, 10.50, now64(3)), "
    "(2, 1, 4.25, now64(3)), (3, 2, 99.00, now64(3))",
    "INSERT INTO {db}.types_demo VALUES (1, ['a', 'b'], {{'k': 1}}, (1, 'x'), "
    "1.50, now64(3), NULL, '00000000-0000-0000-0000-000000000001')",
)
