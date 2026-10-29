# Design notes

## Shape

One package, plugin name `clickhouse`, loaded through the `harlequin.adapter`
entry point. No change to Harlequin itself.

```text
conn_str + CLI options
        |
        v
build_config()  -- scheme, port, or --interface picks the protocol
        |
        +-- HTTP    clickhouse-connect   8123 / 8443
        +-- native  clickhouse-driver    9000 / 9440 (and the default)
        |
        v
ClickHouseConnection: execute, get_catalog, get_completions, cancel
```

`drivers.py` is the only code that knows which client library is in use.
Limits, error mapping, and catalog building sit above it.

## Connection

`connect()` runs `SELECT 1` and raises `HarlequinConnectionError` on failure.
`ClickHouseConnection.conn` exists before the handshake, so a failed connect
never surfaces as an `AttributeError`.

`read_only=True` (`IMPLEMENTS_READ_ONLY`) sends the session setting
`readonly=1`, so the server refuses writes. Unknown options are ignored.

## Catalog

ClickHouse has no schemas: databases, then tables and views, then columns.
Three queries against `system.databases`, `system.tables`, and
`system.columns` build the whole tree. `system` and the information schemas
are hidden. Each column has a 1-3 character `type_label` and the full
ClickHouse type in `type_name`.

## Limits

`set_limit(n)` wraps `SELECT` and `WITH` in
`SELECT * FROM (...) LIMIT n`, so the server stops after `n` rows. If the
wrapped query fails, the original runs and the result is sliced. Other
row-returning statements are sliced client-side.

## Cancel

Each statement gets a query id. `cancel()` sends `KILL QUERY` for that id on a
side connection. Over HTTP the id goes in the URL settings, not a header,
because ClickHouse ignores a `query_id` header. The original connection stays
usable.

## Values

Arrays, maps, tuples, and UUIDs are returned as Python objects. Bytes are
decoded as UTF-8.

## Not in scope

chDB or clickhouse-local, connection pooling, catalog search, and the export
dialog.
