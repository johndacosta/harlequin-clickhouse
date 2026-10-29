from __future__ import annotations

from harlequin.options import FlagOption, ListOption, SelectOption, TextOption


def _validate_port(raw: str | None) -> tuple[bool, str | None]:
    # Click calls the validator with None when the flag was not passed.
    if raw is None or raw == "":
        return True, None
    if raw.isdigit() and 0 < int(raw) < 65536:
        return True, None
    return False, "Port must be an integer between 1 and 65535."


HOST = TextOption(
    name="host",
    description="ClickHouse server host.",
    short_decls=["-H"],
)

PORT = TextOption(
    name="port",
    description=(
        "ClickHouse port. 8123/8443 use HTTP and 9000/9440 use the native "
        "protocol. Other ports use the native protocol unless --interface "
        "says otherwise. Omit this to use 8123."
    ),
    short_decls=["-p"],
    validator=_validate_port,
)

USER = TextOption(
    name="user",
    description="ClickHouse user name.",
    short_decls=["-u"],
)

PASSWORD = TextOption(
    name="password",
    description="ClickHouse password.",
    short_decls=["-W"],
    secret=True,
)

DATABASE = TextOption(
    name="database",
    description="Database to use after connecting.",
    short_decls=["-d"],
)

SECURE = FlagOption(
    name="secure",
    description="Use TLS (a secure connection) for HTTP or the native protocol.",
)

INTERFACE = SelectOption(
    name="interface",
    description=(
        "Wire protocol: http or native. Inferred from the port when omitted "
        "(8123/8443 HTTP, 9000/9440 native)."
    ),
    choices=["http", "native"],
)

NO_VERIFY = FlagOption(
    name="no-verify",
    description="Disable TLS certificate verification.",
)

CA_CERT = TextOption(
    name="ca-cert",
    description="Path to a CA bundle for TLS verification.",
)

COMPRESSION = FlagOption(
    name="compression",
    description="Compress ClickHouse traffic (LZ4).",
)

CLIENT_NAME = TextOption(
    name="client-name",
    description="Client name reported in system.processes.",
)

SETTING = ListOption(
    name="setting",
    description=(
        "Repeatable ClickHouse setting as key=value. Pass --setting more than once."
    ),
    short_decls=["-s"],
)

CLICKHOUSE_OPTIONS = [
    HOST,
    PORT,
    USER,
    PASSWORD,
    DATABASE,
    SECURE,
    INTERFACE,
    NO_VERIFY,
    CA_CERT,
    COMPRESSION,
    CLIENT_NAME,
    SETTING,
]
