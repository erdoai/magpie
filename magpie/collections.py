"""Typed values for collection documents.

A document's value is JSONB but declares its type in ``value_type`` so
agents and adapters can deserialize without guessing. Writes validate the
value against the declared type and reject mismatches.

Types: json (default — objects/arrays/anything), string, integer, float,
boolean, datetime (ISO 8601 string).
"""

from datetime import datetime

VALUE_TYPES = ("json", "string", "integer", "float", "boolean", "datetime")


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
