# ClickHouse server adapter

## Verdict

A ClickHouse **server** client is possible on today's Harlequin adapter plugin
architecture. The entry-point group is `harlequin.adapter`. The classes are
`HarlequinAdapter`, `HarlequinConnection`, and `HarlequinCursor`. No edits to
Harlequin core are required, and this package does not add one.

It must be its own installable package, the same pattern as
[harlequin-questdb](https://github.com/rhuygen/harlequin-questdb) and the
Harlequin adapter guide. It must stay distinct from the existing chDB adapter.
Harlequin already ships a `chdb` extra for local, in-process ClickHouse
(`clickhouse-local` / chDB). chDB does not open a ClickHouse server, and this
package does not embed one.

Neither local tree is sufficient alone:

- PyPI `harlequin-clickhouse` 0.1.1 (ThomAub / `harlequin-clickhouse`) is
  native-only, defaults to port 9000, ships placeholder completions
  (`foo` / `bar` / `baz`), and is the line that raised
  `'HarlequinClickHouseConnection' object has no attribute 'conn'` on launch.
- PyPI `harlequin-clickhouse-adapter` 0.1.2 (Artem Gromov) has TLS,
  compression, repeatable settings, cancel, and a real `system` catalog, but
  its tests mock the driver and it does not speak HTTP.

New unified work is required. Effort is attainable in one package at about
**3–6 engineer-days**, not a core rewrite. Because that verdict is attainable,
this repository is the build, not a note that stops before code.

Do not publish this project to PyPI. Do not squat the taken names
`harlequin-clickhouse` or `harlequin-clickhouse-adapter`. A third published
name would split users. The source of truth is
`github.com/johndacosta/harlequin-clickhouse`. An upstream merge into either
existing package is follow-on work, not this tree.

## Architecture

One distribution, plugin name `clickhouse`, selected with
`harlequin -a clickhouse`.

```text
conn_str + CLI options
        |
        v
ClickHouseAdapter.connect()
        |
        v
build_config()  -- port and scheme pick the protocol
        |
        +-- HTTP   clickhouse-connect   ports 8123 / 8443
        |
        +-- native clickhouse-driver    ports 9000 / 9004 / 9440
        |
        v
ClickHouseConnection
   execute / get_catalog / get_completions / cancel
```

The two connection strings in the homenetwork `docs/CLICKHOUSE.md` carry no
extra flags. The port is the discriminator when the scheme is `clickhouse`:

| URL | Protocol |
| --- | --- |
| `clickhouse://clickhouse:clickhouse@127.0.0.1:8123/sample_db` | HTTP |
| `clickhouse://clickhouse:clickhouse@127.0.0.1:9004/sample_db` | native |

Host port 9000 on the development machines is QuestDB. Native ClickHouse is
published on host port **9004** (container port 9000). When the URL omits a
port, the adapter uses HTTP **8123**. It does not default to host port 9000.
`--interface http|native` overrides the inference. `--port 9004` with no
interface is still native.

`clickhouse-driver` speaks native TCP only, so HTTP is a second driver
(`clickhouse-connect`), behind one small seam. Limit wrapping, error mapping,
and catalog type labels live above that seam. Gating tests call the seam
against the real server, not a mock.

### Connection lifecycle

`ClickHouseConnection.conn` is assigned before the handshake and is set to
`None` if the handshake fails. Later `get_catalog` / `execute` calls raise
`HarlequinConnectionError` or `HarlequinQueryError`. They do not raise
`AttributeError` for a missing `conn`. A failed handshake raises
`HarlequinConnectionError` from `connect()`. A statement ClickHouse rejects
raises `HarlequinQueryError`.

`read_only=True` is a real constructor argument (`IMPLEMENTS_READ_ONLY`).
Harlequin only passes it for adapters that declare the flag. The adapter also
accepts it when constructed directly, so the call cannot raise `TypeError`.
When it is true, the session setting `readonly=1` is sent. Unknown keyword
options are ignored.

### Catalog, limit, cancel, completions

ClickHouse has no schemas. Databases are the top catalog level, then tables
and views, then columns, from `system.databases`, `system.tables`, and
`system.columns`. Column `type_label` and `type_name` keep the ClickHouse type
string (`Array`, `Map`, `Tuple`, `Decimal`, `DateTime64`, `Nullable`, …).
`system` and `INFORMATION_SCHEMA` are omitted so the tree stays usable.

`set_limit(n)` is applied when the cursor fetches. `SELECT` and `WITH` are
wrapped in `SELECT * FROM (...) AS _harlequin_limit LIMIT n` so the server
stops. Other row-returning statements are sliced client-side. `n <= 0`
returns column metadata and no rows.

Cancel is enabled (`IMPLEMENTS_CANCEL`). The in-flight statement is tagged
with a query id. On HTTP that id is a URL parameter (`settings`), not an
HTTP header: ClickHouse ignores a header named `query_id` and assigns its
own, so `KILL QUERY` would miss. `cancel()` issues `KILL QUERY` on a side
connection and returns. The original connection stays usable for a later
`SELECT 1`.

Completions are real ClickHouse keywords and functions (`ARRAY JOIN`,
`arrayJoin`, `toDateTime64`, and the rest of the set in `completions.py`).
They are not placeholders.

### CLI

`harlequin -a clickhouse` exposes host, port, user, password, database,
TLS / `secure`, and repeatable `--setting key=value`, plus interface,
compression, certificate verification, and a CA path. Password is a secret
option. TLS flags are accepted and forwarded. This dev server is plaintext on
8123 and 9004, so a live TLS handshake is out of scope.

### hsql (the agent CLI)

[hsql](https://harlequin.sh) is Harlequin's headless SQL client and the command
an agent should shell out to. It loads this plugin through the same
`harlequin.adapter` entry point as the TUI. `hsql --info -a clickhouse` reports
`implements_read_only` and `implements_cancel` without connecting.
`hsql --help -a clickhouse` and `hsql --spec -a clickhouse` list the options.
This package does not add an MCP server. An agent or an MCP server should run
`hsql`, or call the Python functions below.

ClickHouse has no schemas. `hsql --catalog` walks three levels, not four:

| Invocation | What comes back |
| --- | --- |
| `--catalog` | databases |
| `--catalog --path sample_db` | tables and views |
| `--catalog --path sample_db.types_demo` | columns |

Each row's `query_name` is backtick-quoted ClickHouse SQL. `type` and
`type_label` keep the server type (`Array`, `Map`, `Tuple`, `Decimal`,
`DateTime64`, `Nullable`). `--catalog-search` is not implemented; hsql exits 2
and tells the caller to list one level at a time. A path that assumes a schema
(`sample_db.some_schema.customers`) exits 2 because that middle name is not a
table.

`hsql --limit N` calls `set_limit`. The default is 500, and hsql asks for one
extra row so it can set `"truncated"` in `--stats`. `SELECT` / `WITH` get that
limit in SQL. `--limit -1` does not call `set_limit`. `-r` / `--read-only`
sends `readonly=1`, so a write exits 1 from the server rather than from a
client-side pretend. `--timeout` is honored because cancel is implemented:
hsql refuses the flag on an adapter that cannot stop a query. A rejected
statement exits 1. A bad password exits 3.

Prefer a profile over a password on the command line. See
[HSQL.md](HSQL.md) and `examples/harlequin.toml`.

### Library API for agents

The same connection is importable, for a caller that should not shell out:

- `harlequin_clickhouse.connect(url)`
- `ClickHouseConnection.get_catalog()`
- `ClickHouseConnection.execute()` / cursor `fetchall()`

An agent or an MCP server should call those. This package does not add an MCP
server. ThomAub/clickhouse_mcp_server already exists and is not modified here.

## What this package does not do

- No Harlequin core change, no in-tree adapter, no `harlequin[clickhouse]` extra.
- No chDB or clickhouse-local mode.
- No new MCP server and no LLM chat.
- No PyPI publish.
- No transaction-mode toggle, connection pool, SQL validator, catalog search,
  or copy-format export dialog.
- No MySQL-protocol client, ClickHouse Cloud-only features, or replication
  admin tooling.

## Level of effort

| Slice | Days |
| --- | --- |
| Plugin scaffold, URL/CLI config, native connect/execute/errors | 1–1.5 |
| HTTP driver and port dispatch | 0.5–1 |
| `system` catalog with real ClickHouse type labels | 0.5–1 |
| Completions, cancel, read-only, limit | 0.5–1 |
| Live tests against the Docker sample database, lint, docs | 0.5–1.5 |
| **Total** | **3–6 engineer-days** |

The work that landed here is that package: both protocols, catalog, limit,
DDL, completions, cancel, CLI, and the agent-facing `connect` function.
