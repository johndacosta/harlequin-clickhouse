# ClickHouse through hsql

`hsql` is Harlequin's headless SQL client. Agents should use it for ClickHouse
instead of inventing a client. This package registers the `clickhouse` adapter.
`hsql` and `harlequin` load that same entry point.

This package does not add an MCP server. A shell agent runs `hsql`. A Python
agent calls `connect`, `get_catalog`, and `execute` (see the README). Either
one is enough. ThomAub/clickhouse_mcp_server is a different project and is not
wrapped here.

## Orient before writing SQL

Nothing below connects except `--catalog` and `-c` / `-f`.

```bash
hsql --info -a clickhouse          # versions and declared capabilities
hsql --help -a clickhouse          # host, port, user, password, database, TLS, setting
hsql --spec -a clickhouse          # the same surface as JSON
```

`implements_read_only` and `implements_cancel` are true, so `-r` and
`--timeout` are accepted. `implements_catalog_search` is false. hsql exits 2
on `--catalog-search` and names `--catalog` as the replacement. Do not walk
the catalog in Python to imitate search.

ClickHouse has no schemas. Three levels:

```bash
hsql -P clickhouse --catalog
hsql -P clickhouse --catalog --path sample_db
hsql -P clickhouse --catalog --path sample_db.types_demo
hsql -P clickhouse --catalog --path 'sample_db.order*'
```

| Column | Use it for |
| --- | --- |
| `path` | The next `--path`. `sample_db` lists tables. `sample_db.customers` lists columns. |
| `name` | The label in that level. |
| `query_name` | Paste into SQL. Already backtick-quoted. Do not invent quoting. |
| `type` | The ClickHouse type string (`Array(String)`, `Decimal(18, 4)`, `DateTime64(6, 'UTC')`, `Nullable(String)`, `Map(...)`, `Tuple(...)`). |
| `type_label` | The same ClickHouse type, so a short listing still shows Array, Map, Tuple, Decimal, DateTime64, and Nullable. |

`sample_db.analytics.orders` is a Postgres-shaped path. It will not resolve.
The table is `sample_db.orders`.

## Run SQL

```bash
hsql -P clickhouse -c "SELECT currentDatabase()"
hsql -P clickhouse --limit -1 -c "SELECT count() FROM customers"
hsql -P clickhouse -f ./report.sql --result last
hsql -P clickhouse --markdown -c "SELECT customer_id, country FROM customers"
```

`--limit` defaults to 500 and is sent to ClickHouse (`LIMIT` around `SELECT`
and `WITH`). `--stats` on stderr reports `"truncated"`. Read it. Do not
redirect stderr to `/dev/null`. `--limit -1` fetches everything; use it before
a client-side count, or aggregate in SQL.

Useful ClickHouse statements that return rows: `SELECT`, `WITH`, `SHOW`,
`DESCRIBE`, `EXPLAIN`. `INSERT`, `CREATE`, `ALTER`, and `DROP` return no
result set. Several statements separated by `;` run in order.
`--on-error stop` is the default.

## Writes, cancel, and exit codes

| Code | Meaning |
| --- | --- |
| 0 | The statement ran. |
| 1 | ClickHouse rejected the SQL, including a write under `-r`. |
| 2 | Bad flag, unknown catalog path, or `--catalog-search`. |
| 3 | Could not connect (host, port, user, password, TLS). |
| 4 | `--timeout` fired. The in-flight query is cancelled by query id. |

```bash
hsql -P clickhouse -r -c "SELECT 1"          # allowed
hsql -P clickhouse -r -c "DROP TABLE customers"  # exit 1, server-side readonly=1
hsql -P clickhouse --timeout 30 -c "SELECT 1"
```

`-r` is the server setting `readonly=1`, not a filter in this process. Pass
it before any DDL. Say what a write will change and get agreement first; hsql
will not ask for you.

`--no-write-history` keeps one run out of the local query history. `--history`
reads that history without connecting.

## Profiles

Do not put the password on the command line. `-P None` skips every config
file and is what a test should use. A profile belongs in `harlequin.toml`:

```toml
[profiles.clickhouse]
adapter = "clickhouse"
conn_str = ["clickhouse://127.0.0.1:8123/sample_db"]
user = "clickhouse"
password = "${CLICKHOUSE_PASSWORD}"
read_only = true
limit = 500

[profiles.clickhouse_native]
adapter = "clickhouse"
conn_str = ["clickhouse://127.0.0.1:9004/sample_db"]
user = "clickhouse"
password = "${CLICKHOUSE_PASSWORD}"
```

Port **8123** is HTTP. Port **9004** is native TCP (container port 9000).
Leaving the port out selects HTTP 8123. Host port 9000 is the wrong default
on machines where another database already owns it. `--interface http` or
`--interface native` overrides the guess. `--secure` turns on TLS and is
forwarded; this dev server is plaintext.

Repeat a setting when a query needs one:

```bash
hsql -P clickhouse --setting max_threads=4 --setting join_use_nulls=true -c "SELECT 1"
```

In TOML the same option is `setting = ["max_threads=4", "join_use_nulls=true"]`.

A full example file is `examples/harlequin.toml`. It does not set
`default_profile`.

## What to hand back to a person

A path you cannot disambiguate, a query they will iterate, a destructive
statement, or a result too wide to read: stop and tell them to open

```bash
harlequin -P clickhouse
```

That is the same profile, adapter, and server, with the editor and the grid.
