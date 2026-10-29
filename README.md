# harlequin-clickhouse

A [Harlequin](https://harlequin.sh) adapter for a **ClickHouse server**, over
HTTP or the native TCP protocol. For local, in-process ClickHouse, use the
[chDB adapter](https://harlequin.sh/docs/chdb) instead.

## Install

```bash
uv tool install harlequin --with "harlequin-clickhouse @ git+https://github.com/johndacosta/harlequin-clickhouse"
```

## Connect

```bash
harlequin -a clickhouse "clickhouse://user:password@localhost:9000/default"
harlequin -a clickhouse "clickhouse://user:password@localhost:8123/default"
```

The port picks the protocol: 8123 and 8443 use HTTP, 9000 and 9440 use the
native protocol. With no port, the adapter uses native 9000 (9440 with
`--secure`). For any other port, add `--interface http` or
`--interface native`.

The same connection as options:

```bash
harlequin -a clickhouse \
  --host localhost --port 8123 \
  --user user --password "$CLICKHOUSE_PASSWORD" \
  --database default \
  --setting max_threads=4
```

| Option | What it does |
| --- | --- |
| `--secure` | Use TLS. |
| `--verify false` / `--no-verify` | Skip TLS certificate checks. |
| `--ca-cert PATH` | CA bundle for TLS. |
| `--compression` | Compress traffic. |
| `--setting key=value` | A ClickHouse setting. Repeat for more. |
| `--connect_timeout N`, `--send_receive_timeout N` | Timeouts in seconds. |
| `--read-only` | Sets ClickHouse `readonly=1` on the server. |

Run `harlequin -a clickhouse --help` for the full list. Options from
`harlequin-clickhouse` 0.1.x keep working.

ClickHouse has no schemas, so the catalog is database, then table or view,
then column. Hover a column to see its full ClickHouse type. Query cancel is
supported on both protocols.

Keep the password out of the process list with a profile that reads it from
the environment. See [examples/harlequin.toml](examples/harlequin.toml).

## hsql

[`hsql`](https://harlequin.sh) runs the same adapter without the full-screen
UI. It suits scripts and agents. See [docs/HSQL.md](docs/HSQL.md).

```bash
hsql -a clickhouse "clickhouse://localhost:8123/default" \
  --user user --password "$CLICKHOUSE_PASSWORD" \
  -c "SELECT 1"
```

## Python

```python
from harlequin_clickhouse import connect

conn = connect("clickhouse://user:password@localhost:8123/default")
catalog = conn.get_catalog()
cursor = conn.execute("SELECT currentDatabase()")
rows = cursor.fetchall() if cursor else None
conn.close()
```

## Develop

```bash
docker run -d --name clickhouse -p 8123:8123 -p 9000:9000 \
  -e CLICKHOUSE_PASSWORD=dev clickhouse/clickhouse-server:24.8
uv sync
CLICKHOUSE_PASSWORD=dev uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

The live tests read `CLICKHOUSE_HOST`, `CLICKHOUSE_HTTP_PORT`,
`CLICKHOUSE_NATIVE_PORT`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`, and
`CLICKHOUSE_TEST_DATABASE`. They create and drop their own database, and skip
when no server answers.

## Credits

This adapter builds on earlier work by
[Thomas Aubry](https://github.com/ThomAub/harlequin-clickhouse)
(`harlequin-clickhouse`) and
[Artem Gromov](https://github.com/artem-gromov/harlequin-clickhouse)
(`harlequin-clickhouse-adapter`), and on
[Harlequin's adapter template](https://github.com/tconbeer/harlequin-adapter-template).
Thank you.
