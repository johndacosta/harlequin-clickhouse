from __future__ import annotations

from harlequin_clickhouse import ClickHouseAdapter
from harlequin_clickhouse.config import build_config

NATIVE = "clickhouse://analyst:secret@127.0.0.1:9000/analytics"
HTTP = "clickhouse://analyst:secret@127.0.0.1:8123/analytics"


def test_native_url_uses_9000() -> None:
    config = build_config([NATIVE], {})
    assert config.interface == "native"
    assert config.port == 9000
    assert config.host == "127.0.0.1"
    assert config.user == "analyst"
    assert config.password == "secret"
    assert config.database == "analytics"


def test_http_url_uses_8123() -> None:
    config = build_config([HTTP], {})
    assert config.interface == "http"
    assert config.port == 8123
    assert config.database == "analytics"


def test_omitted_port_is_http_8123_not_9000() -> None:
    config = build_config(["clickhouse://127.0.0.1/analytics"], {})
    assert config.interface == "http"
    assert config.port == 8123


def test_remapped_port_follows_interface() -> None:
    config = build_config([], {"port": "18123", "interface": "http"})
    assert config.interface == "http"
    assert config.port == 18123


def test_repeatable_settings_and_tls_flag_are_forwarded() -> None:
    config = build_config(
        [HTTP],
        {"secure": True, "setting": ("max_threads=4", "join_use_nulls=true")},
    )
    assert config.secure is True
    assert config.settings["max_threads"] == 4
    assert config.settings["join_use_nulls"] is True


def test_read_only_is_a_setting_and_unknown_options_are_ignored() -> None:
    adapter = ClickHouseAdapter(
        [HTTP],
        read_only=True,
        not_a_real_option=object(),
        limit=50,
    )
    config = build_config(
        adapter.conn_str, adapter.options, read_only=adapter.read_only
    )
    assert config.settings["readonly"] == 1
    assert config.interface == "http"


def test_bad_port_is_a_value_error() -> None:
    try:
        build_config([], {"port": "nope"})
    except ValueError as exc:
        assert "Port" in str(exc)
    else:
        raise AssertionError("expected ValueError")
