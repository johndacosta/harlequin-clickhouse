from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qs, unquote, urlparse

DEFAULT_HOST = "localhost"
DEFAULT_USER = "default"
DEFAULT_DATABASE = "default"
DEFAULT_CLIENT_NAME = "harlequin-clickhouse"

HTTP_PORTS = frozenset({8123, 8443})
NATIVE_PORTS = frozenset({9000, 9440})
HTTP_PORT = 8123
HTTP_SECURE_PORT = 8443
NATIVE_PORT = 9000
NATIVE_SECURE_PORT = 9440

_MISSING = object()


@dataclass(frozen=True)
class ClickHouseConfig:
    """Resolved connection. `interface` is `http` or `native`."""

    host: str
    port: int
    user: str
    password: str
    database: str
    interface: str
    secure: bool
    verify: bool
    compression: bool
    settings: dict[str, Any] = field(default_factory=dict)
    client_name: str = DEFAULT_CLIENT_NAME
    ca_certs: str | None = None

    @property
    def safe_id(self) -> str:
        """Cache key. The password stays out of it."""
        return (
            f"clickhouse://{self.user}@{self.host}:{self.port}/{self.database}"
            f"?interface={self.interface}&secure={int(self.secure)}"
        )


def build_config(
    conn_str: Sequence[str],
    options: Mapping[str, Any],
    *,
    read_only: bool = False,
) -> ClickHouseConfig:
    """Merge a Harlequin conn_str with CLI options.

    Extra keys in `options` are ignored. A missing port becomes HTTP 8123.
    Port 8123/8443 selects HTTP. Port 9000/9440 selects the native protocol.
    Any other port uses the native protocol unless `interface` says otherwise.
    """
    parsed = _parse_conn_str(conn_str)

    host = _first_text(options, "host") or parsed.get("host") or DEFAULT_HOST
    user = (
        _first_text(options, "user", "username") or parsed.get("user") or DEFAULT_USER
    )
    database = (
        _first_text(options, "database", "db")
        or parsed.get("database")
        or DEFAULT_DATABASE
    )

    password_option = _first_present(options, "password")
    if password_option is _MISSING:
        password = parsed.get("password") or ""
    else:
        password = "" if password_option is None else str(password_option)

    secure = _flag(options, "secure") or bool(parsed.get("secure"))
    verify = True if parsed.get("verify") is None else bool(parsed.get("verify"))
    if _flag(options, "no-verify", "no_verify"):
        verify = False
    if _first_present(options, "verify") is not _MISSING:
        explicit_verify = _as_bool(_first_present(options, "verify"))
        if explicit_verify is not None:
            verify = explicit_verify

    compression = _flag(options, "compression") or bool(parsed.get("compression"))

    settings: dict[str, Any] = {}
    raw_parsed_settings = parsed.get("settings")
    if isinstance(raw_parsed_settings, dict):
        settings.update(raw_parsed_settings)
    settings.update(_parse_settings(_first_present(options, "setting", "settings")))
    if read_only:
        settings["readonly"] = 1

    client_name = (
        _first_text(options, "client-name", "client_name")
        or parsed.get("client_name")
        or DEFAULT_CLIENT_NAME
    )
    ca_certs = _first_text(options, "ca-cert", "ca_cert", "ca_certs") or parsed.get(
        "ca_certs"
    )

    port_option = _first_present(options, "port")
    port = (
        _parse_port(port_option) if port_option is not _MISSING else parsed.get("port")
    )
    if port is not None:
        port = _parse_port(port)

    interface = _resolve_interface(
        explicit=_first_text(options, "interface") or parsed.get("interface"),
        scheme=str(parsed.get("scheme") or ""),
        port=port,
    )
    if port is None:
        if interface == "http":
            port = HTTP_SECURE_PORT if secure else HTTP_PORT
        else:
            port = NATIVE_SECURE_PORT if secure else NATIVE_PORT

    return ClickHouseConfig(
        host=str(host),
        port=port,
        user=str(user),
        password=str(password),
        database=str(database),
        interface=interface,
        secure=secure,
        verify=verify,
        compression=compression,
        settings=settings,
        client_name=str(client_name),
        ca_certs=str(ca_certs) if ca_certs else None,
    )


def apply_limit(query: str, limit: int) -> str:
    """Wrap a SELECT/WITH so ClickHouse returns at most `limit` rows."""
    body = query.strip().rstrip(";").strip()
    bounded = max(limit, 0)
    return f"SELECT * FROM (\n{body}\n) AS _harlequin_limit LIMIT {bounded}"


def leading_keyword(query: str) -> str:
    """First SQL word, skipping leading comments and whitespace."""
    remaining = query.lstrip()
    while remaining:
        if remaining.startswith("--"):
            newline = remaining.find("\n")
            remaining = "" if newline < 0 else remaining[newline + 1 :].lstrip()
            continue
        if remaining.startswith("/*"):
            end = remaining.find("*/")
            remaining = "" if end < 0 else remaining[end + 2 :].lstrip()
            continue
        break
    if not remaining:
        return ""
    word = remaining.split(None, 1)[0]
    return word.lower().strip(";(")


def _parse_conn_str(conn_str: Sequence[str]) -> dict[str, Any]:
    if not conn_str:
        return {}
    if len(conn_str) == 1 and "://" in conn_str[0]:
        return _parse_url(conn_str[0])
    return _parse_conn_tokens(conn_str)


def _parse_url(conn_url: str) -> dict[str, Any]:
    parsed = urlparse(conn_url)
    data: dict[str, Any] = {"scheme": (parsed.scheme or "").lower()}
    if parsed.hostname:
        data["host"] = parsed.hostname
    if parsed.port:
        data["port"] = parsed.port
    if parsed.username:
        data["user"] = unquote(parsed.username)
    if parsed.password is not None:
        data["password"] = unquote(parsed.password)
    if parsed.path and parsed.path != "/":
        database = unquote(parsed.path.lstrip("/"))
        if database:
            data["database"] = database

    query = parse_qs(parsed.query, keep_blank_values=True)
    if parsed.scheme.lower() in {"https", "clickhouse+https"}:
        data["secure"] = True
        data["interface"] = "http"
    elif parsed.scheme.lower() in {"http", "clickhouse+http"}:
        data["interface"] = "http"
    elif parsed.scheme.lower() in {
        "tcp",
        "native",
        "clickhouse+native",
        "clickhouse+tcp",
    }:
        data["interface"] = "native"

    secure = _as_bool(_first_query(query, "secure"))
    verify = _as_bool(_first_query(query, "verify"))
    compression = _as_bool(_first_query(query, "compression"))
    if secure is not None:
        data["secure"] = secure
    if verify is not None:
        data["verify"] = verify
    if compression is not None:
        data["compression"] = compression

    interface = _first_query(query, "interface")
    if interface:
        data["interface"] = interface.strip().lower()
    client_name = _first_query(query, "client_name", "client-name")
    if client_name:
        data["client_name"] = client_name
    ca_certs = _first_query(query, "ca_certs", "ca-cert", "ca_cert")
    if ca_certs:
        data["ca_certs"] = ca_certs

    setting_values = query.get("setting", [])
    if setting_values:
        data["settings"] = _parse_settings(setting_values)
    return data


def _parse_conn_tokens(conn_str: Sequence[str]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if len(conn_str) == 1 and ":" in conn_str[0] and "//" not in conn_str[0]:
        host, port = conn_str[0].rsplit(":", 1)
        if host:
            data["host"] = host
        parsed_port = _parse_port(port)
        if parsed_port is not None:
            data["port"] = parsed_port
        return data

    if len(conn_str) >= 1 and conn_str[0]:
        data["host"] = conn_str[0]
    if len(conn_str) >= 2 and conn_str[1]:
        data["port"] = _parse_port(conn_str[1])
    if len(conn_str) >= 3 and conn_str[2]:
        data["database"] = conn_str[2]
    if len(conn_str) >= 4 and conn_str[3]:
        data["user"] = conn_str[3]
    if len(conn_str) >= 5:
        data["password"] = conn_str[4]
    return data


def _resolve_interface(*, explicit: str | None, scheme: str, port: int | None) -> str:
    if explicit in {"http", "https"}:
        return "http"
    if explicit in {"native", "tcp"}:
        return "native"
    if scheme in {"http", "https", "clickhouse+http", "clickhouse+https"}:
        return "http"
    if scheme in {"tcp", "native", "clickhouse+native", "clickhouse+tcp"}:
        return "native"
    if port in HTTP_PORTS:
        return "http"
    if port in NATIVE_PORTS:
        return "native"
    # No port at all: HTTP on 8123. An explicit unusual port stays native so a
    # remapped native listener still works; pass `interface` to choose HTTP.
    if port is None:
        return "http"
    return "native"


def _parse_port(value: Any) -> int | None:
    if value is None or value is False or value == "":
        return None
    if isinstance(value, bool) or isinstance(value, str) and not value.isdigit():
        raise ValueError("Port must be an integer between 1 and 65535.")
    if isinstance(value, int):
        port = value
    elif isinstance(value, str):
        port = int(value)
    else:
        raise ValueError("Port must be an integer between 1 and 65535.")
    if not 1 <= port <= 65535:
        raise ValueError("Port must be an integer between 1 and 65535.")
    return port


def _parse_settings(value: Any) -> dict[str, Any]:
    if value is None or value is _MISSING:
        return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    items: list[str]
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, Iterable):
        items = [str(item) for item in value if item is not None and str(item) != ""]
    else:
        return {}
    settings: dict[str, Any] = {}
    for raw in items:
        if "=" not in raw:
            raise ValueError(f"Invalid setting '{raw}'. Expected key=value.")
        key, raw_value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid setting '{raw}'. Expected key=value.")
        settings[key] = _coerce_setting_value(raw_value.strip())
    return settings


def _coerce_setting_value(value: str) -> Any:
    lower = value.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in {"1", "true", "yes", "y", "on"}:
            return True
        if lower in {"0", "false", "no", "n", "off"}:
            return False
    return None


def _flag(options: Mapping[str, Any], *names: str) -> bool:
    present = _first_present(options, *names)
    if present is _MISSING:
        return False
    return _as_bool(present) is True


def _first_text(options: Mapping[str, Any], *names: str) -> str | None:
    present = _first_present(options, *names)
    if present is _MISSING or present is None:
        return None
    if isinstance(present, str):
        text = present.strip()
        return text or None
    if isinstance(present, bool):
        return None
    if isinstance(present, (int, float)):
        return str(present)
    return None


def _first_present(options: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in options:
            return options[name]
    return _MISSING


def _first_query(query: Mapping[str, list[str]], *names: str) -> str | None:
    for name in names:
        values = query.get(name)
        if values:
            return values[0]
    return None
