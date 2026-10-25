# harlequin-clickhouse

Harlequin adapter for a **ClickHouse server**. HTTP and the native TCP
protocol. This is a separate installable package (the same shape as
[harlequin-questdb](https://github.com/rhuygen/harlequin-questdb)). It is not
an in-tree Harlequin change, and it is not the chDB / `clickhouse-local`
extra Harlequin already ships.

The design record is [docs/DESIGN.md](docs/DESIGN.md): possible on today's
`harlequin.adapter` plugin, about **3–6 engineer-days**, and **do not squat**
the taken PyPI names `harlequin-clickhouse` or `harlequin-clickhouse-adapter`.
Install from this Git repository. Do not publish this tree to PyPI.

## Credits

Two existing adapters were the inputs, and neither was enough on its own:

- [ThomAub/harlequin-clickhouse](https://github.com/ThomAub/harlequin-clickhouse)
  (PyPI `harlequin-clickhouse` 0.1.1) — native protocol only, default port
  9000, placeholder completions, and the launch bug
  `'HarlequinClickHouseConnection' object has no attribute 'conn'`.
- [Artem Gromov's harlequin-clickhouse-adapter](https://pypi.org/project/harlequin-clickhouse-adapter/)
  (PyPI `harlequin-clickhouse-adapter` 0.1.2) — TLS, compression, repeatable
  settings, cancel, and a `system` catalog. Tests mock the driver. No HTTP.

This package keeps Artem's server features, speaks HTTP as well as native,
preserves ClickHouse type names in the catalog, and ships real completions.

## Install

```bash
uv pip install "harlequin>=1.25,<3" \
  "harlequin-clickhouse @ git+https://github.com/johndacosta/harlequin-clickhouse"
```

## Harlequin

```bash
harlequin -a clickhouse \
  "clickhouse://clickhouse:clickhouse@127.0.0.1:8123/sample_db"
```

The same URL on port **9004** uses the native protocol. Port **8123** uses
HTTP. You do not pass an extra flag to choose. Host port 9000 is not the
default: on the machines this was built against, 9000 is QuestDB and native
ClickHouse is published on **9004**.

```bash
harlequin -a clickhouse --help
```

The help lists host, port, user, password, database, TLS / `--secure`, and
repeatable `--setting key=value`.

```text
harlequin -a clickhouse \
  --host 127.0.0.1 --port 8123 \
  --user clickhouse --password clickhouse \
  --database sample_db \
  --setting max_threads=4
```

`--interface native` or `--interface http` overrides the port guess.
`--secure` turns on TLS and is forwarded to the driver. `--read-only` sets
ClickHouse `readonly=1`.

## hsql

`hsql` is the headless client and the command an agent should run. Same
adapter, same options, no full-screen UI. ClickHouse has no schemas, so the
catalog is database, then table or view, then column. The details, the exit
codes, and a profile that keeps the password out of the process list are in
[docs/HSQL.md](docs/HSQL.md).

```bash
hsql -P None -a clickhouse \
  "clickhouse://127.0.0.1:8123/sample_db" \
  --user clickhouse --password "$CLICKHOUSE_PASSWORD" \
  --catalog --path sample_db

hsql -P None -a clickhouse \
  "clickhouse://127.0.0.1:9004/sample_db" \
  --user clickhouse --password "$CLICKHOUSE_PASSWORD" \
  --limit 500 --stats \
  -c "SELECT count() FROM customers"
```

`-P None` ignores config files. `-r` is server-side `readonly=1`. A bad
statement exits 1. A bad password exits 3. `--catalog-search` exits 2; list
one level with `--catalog --path`.

## Agents and MCP

An agent or an MCP server should run `hsql` (above) or call the installed
package. Do not start a new MCP server for this adapter. Connect, then
catalog, then execute:

```python
from harlequin_clickhouse import connect

conn = connect("clickhouse://clickhouse:clickhouse@127.0.0.1:8123/sample_db")
catalog = conn.get_catalog()
cursor = conn.execute("SELECT currentDatabase()")
assert cursor is not None
rows = cursor.fetchall()
conn.close()
```

`get_catalog()` lists databases, tables, views, and columns. Column labels
keep ClickHouse types (`Array`, `Map`, `Tuple`, `Decimal`, `DateTime64`,
`Nullable`). `cursor.set_limit(n)` bounds the fetched rows.
`conn.get_completions()` returns real ClickHouse tokens such as `arrayJoin`,
`ARRAY JOIN`, and `toDateTime64`. `conn.cancel()` kills the in-flight query
id and leaves the connection usable.

The same calls work for the native URL
`clickhouse://clickhouse:clickhouse@127.0.0.1:9004/sample_db`.

A bad password raises `HarlequinConnectionError`. A statement ClickHouse
rejects raises `HarlequinQueryError` when the cursor is fetched (or
immediately for DDL). A successful connection always has a `conn` attribute.

## Sample database

The URLs above match the homenetwork ClickHouse stack (`sample_db`, user
`clickhouse`, password `clickhouse`). Those are documented sample
credentials, not a secret to copy into this repo.
