"""Typed values for kv pairs.

A pair's value is JSONB but declares its type in ``value_type`` so
agents and adapters can deserialize without guessing. Writes validate the
value against the declared type and reject mismatches.

Types: json (default — objects/arrays/anything), string, integer, float,
boolean, datetime (ISO 8601 string).
"""

from datetime import datetime

VALUE_TYPES = ("json", "string", "integer", "float", "boolean", "datetime")


def kv_value_changed(previous: dict | None, value, value_type: str, summary) -> bool:
    """Whether setting ``(value, value_type, summary)`` materially changes an
    existing pair — the basis for a KV revision. False for a brand-new key.
    A None summary is "leave as-is" (set_kv_pair COALESCEs it), so it's only a
    change when explicitly provided and different."""
    if previous is None:
        return False
    if previous.get("value") != value or previous.get("value_type") != value_type:
        return True
    return summary is not None and previous.get("summary") != summary


def infer_value_type(value) -> str:
    """Infer a ``value_type`` from a native JSON value.

    Used when loading repo-canonical kv files, where pairs are
    written as plain JSON. ``datetime`` is never inferred (it is a string on
    the wire and indistinguishable from a plain string) — declare it explicitly
    if needed. ``bool`` is checked before ``int`` because ``True`` is an int.
    """
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    return "json"  # objects, arrays, null


def validate_value(value, value_type: str) -> str | None:
    """Return an error message if the value doesn't match the declared type."""
    if value_type not in VALUE_TYPES:
        return f"Unknown value_type '{value_type}'. One of: {', '.join(VALUE_TYPES)}"

    if value_type == "json":
        return None
    if value_type == "string":
        if not isinstance(value, str):
            return "value_type 'string' requires a JSON string"
        return None
    if value_type == "boolean":
        if not isinstance(value, bool):
            return "value_type 'boolean' requires a JSON boolean"
        return None
    if value_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return "value_type 'integer' requires a JSON integer"
        return None
    if value_type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "value_type 'float' requires a JSON number"
        return None
    # datetime
    if not isinstance(value, str):
        return "value_type 'datetime' requires an ISO 8601 string"
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return f"value_type 'datetime' requires an ISO 8601 string, got: {value!r}"
    return None
