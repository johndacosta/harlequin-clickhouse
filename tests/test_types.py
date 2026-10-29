from __future__ import annotations

import pytest

from harlequin_clickhouse.types import short_type


@pytest.mark.parametrize(
    ("type_name", "label"),
    [
        ("Nullable(Int32)", "#"),
        ("LowCardinality(Nullable(String))", "s"),
        ("Array(Tuple(UInt8, String))", "[]"),
        ("DateTime64(3, 'UTC')", "ts"),
    ],
)
def test_short_type_labels(type_name: str, label: str) -> None:
    assert short_type(type_name) == label
