from __future__ import annotations

from threading import Lock
from typing import Any, Mapping, Sequence
from uuid import uuid4

from harlequin import HarlequinAdapter, HarlequinConnection, HarlequinCursor
from harlequin.autocomplete.completion import HarlequinCompletion
from harlequin.catalog import Catalog, CatalogItem
from harlequin.exception import HarlequinConnectionError, HarlequinQueryError

from harlequin_clickhouse.cli_options import CLICKHOUSE_OPTIONS
from harlequin_clickhouse.completions import clickhouse_completions
from harlequin_clickhouse.config import (
    ClickHouseConfig,
    apply_limit,
    build_config,
    leading_keyword,
)
from harlequin_clickhouse.drivers import ClickHouseDriver, QueryResult, open_driver

ROW_RETURNING = frozenset({"select", "with", "show", "describe", "desc", "explain"})
WRAPPABLE = frozenset({"select", "with"})
HIDDEN_DATABASES = frozenset({"system", "information_schema", "INFORMATION_SCHEMA"})

_CONNECT_TITLE = "Harlequin could not connect to ClickHouse."
_QUERY_TITLE = "ClickHouse rejected the query."
_CATALOG_TITLE = "Harlequin could not load the ClickHouse catalog."


def _quote(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"


def _relation_label(engine: str) -> str:
    normalized = engine.lower().replace(" ", "")
    if "materializedview" in normalized:
        return "mv"
    if normalized.endswith("view"):
        return "v"
    if "dictionary" in normalized:
        return "d"
    return "t"


class ClickHouseCursor(HarlequinCursor):
    def __init__(self, connection: ClickHouseConnection, query: str) -> None:
        self._connection = connection
        self._query = query
        self._limit: int | None = None
        self._rows: list[tuple[Any, ...]] | None = None
        self._columns: list[tuple[str, str]] = []
        self._ready = False

    def columns(self) -> list[tuple[str, str]]:
        self._ensure()
        return list(self._columns)

    def set_limit(self, limit: int) -> ClickHouseCursor:
        self._limit = limit
        self._ready = False
        return self

    def fetchall(self) -> list[tuple[Any, ...]] | None:
        self._ensure()
        if not self._rows:
            return None
        return self._rows

    def _ensure(self) -> None:
        if self._ready:
            return
        keyword = leading_keyword(self._query)
        sql = self._query
        wrapped = False
        if self._limit is not None and keyword in WRAPPABLE:
            sql = apply_limit(self._query, self._limit)
            wrapped = True
        try:
            result = self._connection._query_once(sql)
        except HarlequinQueryError:
            if not wrapped:
                raise
            result = self._connection._query_once(self._query)
        rows = result.rows
        if self._limit is not None and self._limit >= 0:
            rows = rows[: self._limit]
        elif self._limit is not None and self._limit < 0:
            rows = []
        self._rows = rows
        self._columns = [(name, type_name) for name, type_name in result.columns]
        self._ready = True


class ClickHouseConnection(HarlequinConnection):
    def __init__(self, config: ClickHouseConfig, *, init_message: str = "") -> None:
        # `conn` exists before the handshake so a failed connect cannot raise
        # AttributeError: '...' object has no attribute 'conn'.
        self.init_message = init_message
        self.conn: ClickHouseDriver | None = None
        self._config = config
        self._lock = Lock()
        self._query_lock = Lock()
        self._current_query_id: str | None = None
        try:
            driver = open_driver(config)
            self.conn = driver
            driver.query("SELECT 1", query_id=uuid4().hex)
        except Exception as exc:
            self._discard_driver()
            raise HarlequinConnectionError(msg=str(exc), title=_CONNECT_TITLE) from exc

    def close(self) -> None:
        self._discard_driver()

    def execute(self, query: str) -> ClickHouseCursor | None:
        self._require_driver()
        if leading_keyword(query) not in ROW_RETURNING:
            self._command(query)
            return None
        return ClickHouseCursor(self, query)

    def get_catalog(self) -> Catalog:
        hidden = ", ".join(f"'{name}'" for name in sorted(HIDDEN_DATABASES))
        try:
            databases = self._query_once(
                "SELECT name FROM system.databases "
                f"WHERE name NOT IN ({hidden}) ORDER BY name"
            )
            tables = self._query_once(
                "SELECT database, name, engine FROM system.tables "
                f"WHERE is_temporary = 0 AND database NOT IN ({hidden}) "
                "ORDER BY database, name"
            )
            columns = self._query_once(
                "SELECT database, table, name, type FROM system.columns "
                f"WHERE database NOT IN ({hidden}) "
                "ORDER BY database, table, position"
            )
        except HarlequinQueryError:
            raise
        except Exception as exc:
            raise HarlequinQueryError(msg=str(exc), title=_CATALOG_TITLE) from exc
        return Catalog(items=_catalog_items(databases, tables, columns))

    def get_completions(self) -> list[HarlequinCompletion]:
        return clickhouse_completions()

    def cancel(self) -> None:
        with self._query_lock:
            query_id = self._current_query_id
        driver = self.conn
        if not query_id or driver is None:
            return
        driver.cancel(query_id)

    def _command(self, sql: str) -> None:
        driver = self._require_driver()
        query_id = uuid4().hex
        with self._query_lock:
            self._current_query_id = query_id
        try:
            with self._lock:
                driver.command(sql, query_id=query_id)
        except HarlequinQueryError:
            raise
        except Exception as exc:
            raise HarlequinQueryError(msg=str(exc), title=_QUERY_TITLE) from exc
        finally:
            with self._query_lock:
                self._current_query_id = None

    def _query_once(self, sql: str) -> QueryResult:
        driver = self._require_driver()
        query_id = uuid4().hex
        with self._query_lock:
            self._current_query_id = query_id
        try:
            with self._lock:
                return driver.query(sql, query_id=query_id)
        except HarlequinQueryError:
            raise
        except Exception as exc:
            raise HarlequinQueryError(msg=str(exc), title=_QUERY_TITLE) from exc
        finally:
            with self._query_lock:
                self._current_query_id = None

    def _require_driver(self) -> ClickHouseDriver:
        if self.conn is None:
            raise HarlequinConnectionError(
                msg="Not connected to ClickHouse.",
                title=_CONNECT_TITLE,
            )
        return self.conn

    def _discard_driver(self) -> None:
        driver = self.conn
        self.conn = None
        if driver is None:
            return
        try:
            driver.close()
        except Exception:
            return


def _catalog_items(
    databases: QueryResult,
    tables: QueryResult,
    columns: QueryResult,
) -> list[CatalogItem]:
    by_database: dict[str, dict[str, dict[str, Any]]] = {}
    for row in tables.rows:
        if len(row) < 3:
            continue
        database, table, engine = str(row[0]), str(row[1]), str(row[2])
        by_database.setdefault(database, {})[table] = {"engine": engine, "columns": []}

    for row in columns.rows:
        if len(row) < 4:
            continue
        database, table, column, col_type = (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
        )
        relations = by_database.setdefault(database, {})
        entry = relations.setdefault(table, {"engine": "", "columns": []})
        entry["columns"].append((column, col_type))

    items: list[CatalogItem] = []
    seen: set[str] = set()
    ordered = [str(row[0]) for row in databases.rows if row]
    for database in by_database:
        if database not in ordered:
            ordered.append(database)
    for database in ordered:
        if database in seen:
            continue
        seen.add(database)
        relation_items: list[CatalogItem] = []
        for table, meta in sorted(by_database.get(database, {}).items()):
            column_items = [
                CatalogItem(
                    qualified_identifier=(
                        f"{_quote(database)}.{_quote(table)}.{_quote(column)}"
                    ),
                    query_name=_quote(column),
                    label=column,
                    type_label=col_type,
                    type_name=col_type,
                )
                for column, col_type in meta["columns"]
            ]
            relation_items.append(
                CatalogItem(
                    qualified_identifier=f"{_quote(database)}.{_quote(table)}",
                    query_name=f"{_quote(database)}.{_quote(table)}",
                    label=table,
                    type_label=_relation_label(str(meta["engine"])),
                    type_name=str(meta["engine"]) or None,
                    children=column_items,
                )
            )
        items.append(
            CatalogItem(
                qualified_identifier=_quote(database),
                query_name=_quote(database),
                label=database,
                type_label="db",
                type_name="database",
                children=relation_items,
            )
        )
    return items


class ClickHouseAdapter(HarlequinAdapter):
    ADAPTER_OPTIONS = CLICKHOUSE_OPTIONS
    IMPLEMENTS_CANCEL = True
    IMPLEMENTS_READ_ONLY = True
    ADAPTER_DETAILS = (
        "ClickHouse server over HTTP (`clickhouse-connect`) or native TCP "
        "(`clickhouse-driver`). Not the embedded chDB adapter."
    )

    def __init__(
        self,
        conn_str: Sequence[str],
        read_only: bool = False,
        **options: Any,
    ) -> None:
        self.conn_str = list(conn_str)
        self.read_only = bool(read_only)
        # Supersets of the declared options arrive from Harlequin. Keep them
        # and let build_config read only the keys it understands.
        self.options: Mapping[str, Any] = options

    def connect(self) -> ClickHouseConnection:
        try:
            config = build_config(
                self.conn_str,
                self.options,
                read_only=self.read_only,
            )
        except ValueError as exc:
            raise HarlequinConnectionError(msg=str(exc), title=_CONNECT_TITLE) from exc
        message = (
            f"Connected to ClickHouse at {config.host}:{config.port}"
            f"/{config.database} over {config.interface}."
        )
        return ClickHouseConnection(config, init_message=message)

    @property
    def connection_id(self) -> str | None:
        try:
            return build_config(
                self.conn_str,
                self.options,
                read_only=self.read_only,
            ).safe_id
        except ValueError:
            return None


def connect(
    conn_str: str | Sequence[str],
    /,
    *,
    read_only: bool = False,
    **options: Any,
) -> ClickHouseConnection:
    """Open a connection.

    Agents and MCP servers should call this, then `get_catalog` and `execute`.
    This package does not add an MCP server.
    """
    strings: Sequence[str] = [conn_str] if isinstance(conn_str, str) else conn_str
    return ClickHouseAdapter(strings, read_only=read_only, **options).connect()
