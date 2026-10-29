from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from harlequin_clickhouse.config import ClickHouseConfig


@dataclass(frozen=True)
class QueryResult:
    rows: list[tuple[Any, ...]]
    columns: list[tuple[str, str]]


class ClickHouseDriver(Protocol):
    def query(self, sql: str, *, query_id: str) -> QueryResult: ...

    def command(self, sql: str, *, query_id: str) -> None: ...

    def cancel(self, query_id: str) -> None: ...

    def close(self) -> None: ...


def open_driver(config: ClickHouseConfig) -> ClickHouseDriver:
    if config.interface == "http":
        return HttpDriver(config)
    return NativeDriver(config)


def _cell(value: Any) -> Any:
    """Make a value the results grid can show as a typed column.

    Bytes become text. A tuple becomes a dict keyed by element position
    ("1", "2", ...), as in ClickHouse's ``t.1``, so the grid shows it as a
    struct the way Harlequin shows DuckDB structs. A tuple with mixed
    element types would otherwise turn the whole grid into plain text.
    Arrays, maps, and UUIDs stay Python objects.
    """
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, tuple):
        return {str(i): _cell(v) for i, v in enumerate(value, start=1)}
    if isinstance(value, list):
        return [_cell(v) for v in value]
    if isinstance(value, dict):
        return {k: _cell(v) for k, v in value.items()}
    return value


def _rows(raw: Any) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for row in raw or []:
        if isinstance(row, (tuple, list)):
            rows.append(tuple(_cell(item) for item in row))
        else:
            rows.append((_cell(row),))
    return rows


def _type_name(type_obj: Any) -> str:
    if isinstance(type_obj, str):
        return type_obj
    for attr in ("name", "base_type"):
        value = getattr(type_obj, attr, None)
        if isinstance(value, str) and value:
            return value
    text = str(type_obj)
    return text


def _columns(raw: Any) -> list[tuple[str, str]]:
    columns: list[tuple[str, str]] = []
    for item in raw or []:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            columns.append((str(item[0]), _type_name(item[1])))
        else:
            name = getattr(item, "name", None)
            type_obj = getattr(item, "type", item)
            columns.append((str(name or ""), _type_name(type_obj)))
    return columns


def _safe_query_id(query_id: str) -> str:
    return "".join(character for character in query_id if character.isalnum())


class NativeDriver:
    """clickhouse-driver Client. Native TCP only."""

    def __init__(self, config: ClickHouseConfig) -> None:
        from clickhouse_driver import Client

        kwargs: dict[str, Any] = {
            "host": config.host,
            "port": config.port,
            "user": config.user,
            "password": config.password,
            "database": config.database,
            "secure": config.secure,
            "compression": config.compression,
            "client_name": config.client_name,
            "settings": config.settings or None,
        }
        if config.connect_timeout is not None:
            kwargs["connect_timeout"] = config.connect_timeout
        if config.send_receive_timeout is not None:
            kwargs["send_receive_timeout"] = config.send_receive_timeout
        if config.secure:
            kwargs["verify"] = config.verify
            if config.ca_certs:
                kwargs["ca_certs"] = config.ca_certs
        self._config = config
        self._client: Any = Client(**kwargs)

    def query(self, sql: str, *, query_id: str) -> QueryResult:
        data, columns = self._client.execute(
            sql,
            with_column_types=True,
            query_id=query_id,
        )
        return QueryResult(rows=_rows(data), columns=_columns(columns))

    def command(self, sql: str, *, query_id: str) -> None:
        self._client.execute(sql, query_id=query_id)

    def cancel(self, query_id: str) -> None:
        safe = _safe_query_id(query_id)
        if not safe:
            return
        side: Any | None = None
        try:
            side = NativeDriver(self._config)
            side.command(
                f"KILL QUERY WHERE query_id = '{safe}' SYNC",
                query_id=f"{safe}cancel",
            )
        except Exception:
            return
        finally:
            if side is not None:
                side.close()

    def close(self) -> None:
        disconnect = getattr(self._client, "disconnect", None)
        if callable(disconnect):
            disconnect()


class HttpDriver:
    """clickhouse-connect client. HTTP interface."""

    def __init__(self, config: ClickHouseConfig) -> None:
        import clickhouse_connect

        kwargs: dict[str, Any] = {
            "host": config.host,
            "port": config.port,
            "username": config.user,
            "password": config.password,
            "database": config.database,
            "secure": config.secure,
            "verify": config.verify,
            "compress": config.compression,
            "client_name": config.client_name,
            "settings": config.settings or None,
        }
        if config.ca_certs:
            kwargs["ca_cert"] = config.ca_certs
        if config.connect_timeout is not None:
            kwargs["connect_timeout"] = config.connect_timeout
        if config.send_receive_timeout is not None:
            kwargs["send_receive_timeout"] = config.send_receive_timeout
        # Do not let the client invent an id. Cancel names the id we send.
        kwargs["autogenerate_query_id"] = False
        self._config = config
        self._client: Any = clickhouse_connect.get_client(**kwargs)

    def query(self, sql: str, *, query_id: str) -> QueryResult:
        # A URL parameter. transport_settings become HTTP headers, and
        # ClickHouse does not take a header named query_id as the id
        # queryID() returns, so KILL QUERY would miss.
        result: Any = self._client.query(sql, settings={"query_id": query_id})
        names = list(getattr(result, "column_names", ()) or ())
        types = list(getattr(result, "column_types", ()) or ())
        columns = [
            (str(name), _type_name(types[index] if index < len(types) else ""))
            for index, name in enumerate(names)
        ]
        return QueryResult(
            rows=_rows(getattr(result, "result_rows", ())), columns=columns
        )

    def command(self, sql: str, *, query_id: str) -> None:
        self._client.command(sql, settings={"query_id": query_id})

    def cancel(self, query_id: str) -> None:
        safe = _safe_query_id(query_id)
        if not safe:
            return
        side: HttpDriver | None = None
        try:
            side = HttpDriver(self._config)
            side.command(
                f"KILL QUERY WHERE query_id = '{safe}' SYNC",
                query_id=f"{safe}cancel",
            )
        except Exception:
            return
        finally:
            if side is not None:
                side.close()

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()
