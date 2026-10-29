"""Short type labels for the catalog and the results header.

Harlequin shows a 1-3 character label next to each column. The labels follow
the DuckDB adapter where the types match. The full ClickHouse type stays in
``CatalogItem.type_name``.
"""

from __future__ import annotations

_WRAPPERS = ("Nullable(", "LowCardinality(", "SimpleAggregateFunction(")

_LABELS = {
    "Bool": "t/f",
    "Int8": "#",
    "Int16": "#",
    "Int32": "#",
    "Int64": "##",
    "Int128": "###",
    "Int256": "###",
    "UInt8": "u#",
    "UInt16": "u#",
    "UInt32": "u#",
    "UInt64": "u##",
    "UInt128": "u##",
    "UInt256": "u##",
    "Float32": "#.#",
    "Float64": "#.#",
    "BFloat16": "#.#",
    "Decimal": "#.#",
    "Decimal32": "#.#",
    "Decimal64": "#.#",
    "Decimal128": "#.#",
    "Decimal256": "#.#",
    "String": "s",
    "FixedString": "s",
    "Enum8": "e",
    "Enum16": "e",
    "UUID": "uid",
    "IPv4": "ip",
    "IPv6": "ip",
    "Date": "d",
    "Date32": "d",
    "DateTime": "ts",
    "DateTime64": "ts",
    "Time": "t",
    "Time64": "t",
    "Interval": "|-|",
    "Array": "[]",
    "Map": "{m}",
    "Tuple": "()",
    "Nested": "[]",
    "JSON": "{}",
    "Object": "{}",
    "Dynamic": "dyn",
    "Variant": "var",
    "AggregateFunction": "agg",
    "Point": "geo",
    "Ring": "geo",
    "LineString": "geo",
    "MultiLineString": "geo",
    "Polygon": "geo",
    "MultiPolygon": "geo",
    "Nothing": "\\n",
}


def short_type(type_name: str) -> str:
    """A 1-3 character label for a ClickHouse type such as ``Nullable(Int32)``."""
    raw = type_name.strip()
    unwrapped = True
    while unwrapped:
        unwrapped = False
        for wrapper in _WRAPPERS:
            if raw.startswith(wrapper) and raw.endswith(")"):
                raw = raw[len(wrapper) : -1].strip()
                if wrapper == "SimpleAggregateFunction(":
                    raw = raw.split(",", 1)[-1].strip()
                unwrapped = True
    base = raw.split("(", 1)[0].strip()
    if base.startswith("Interval"):
        base = "Interval"
    return _LABELS.get(base, "?")
