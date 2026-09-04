"""Bound and validate MCP tool calls before any corpus or model work."""
from __future__ import annotations

import json
import re
from typing import Any


MAX_ARGUMENT_BYTES = 128 * 1024


class ToolInputError(ValueError):
    """The tool name or arguments do not satisfy the published input contract."""


def _normalise_json(value: Any) -> object:
    """Create a sortable, type-preserving form for any JSON-compatible value."""
    if isinstance(value, dict):
        entries = []
        for key, item in value.items():
            encoded_key = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
            entries.append((type(key).__name__, encoded_key, _normalise_json(item)))
        entries.sort(key=lambda entry: (entry[0], entry[1]))
        return ["object", entries]
    if isinstance(value, (list, tuple)):
        return ["array", [_normalise_json(item) for item in value]]
    return ["scalar", type(value).__name__, value]


def _unique_fingerprint(value: Any) -> str:
    return json.dumps(
        _normalise_json(value),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def validate_tool_call(
    name: Any,
    arguments: Any,
    descriptors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return validated arguments, raising a non-reflective input error.

    MCP SDKs normally validate tool input, but the server also validates at the
    dispatch boundary. This protects direct callers and future transports and
    keeps malformed input away from embedding/model work.
    """
    if not isinstance(name, str) or len(name) > 128:
        raise ToolInputError("unknown tool")
    descriptor = next((item for item in descriptors if item.get("name") == name), None)
    if descriptor is None:
        raise ToolInputError("unknown tool")
    if not isinstance(arguments, dict):
        raise ToolInputError("arguments must be an object")
    try:
        encoded = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ToolInputError("arguments are not JSON-compatible") from exc
    if len(encoded.encode("utf-8")) > MAX_ARGUMENT_BYTES:
        raise ToolInputError("arguments exceed the size limit")
    _validate(arguments, descriptor["inputSchema"], depth=0)
    return arguments


def _validate(value: Any, schema: dict[str, Any], *, depth: int) -> None:
    if depth > 8:
        raise ToolInputError("arguments are nested too deeply")
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise ToolInputError("expected an object")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if any(key not in value for key in required):
            raise ToolInputError("a required argument is missing")
        if schema.get("additionalProperties") is False and any(key not in properties for key in value):
            raise ToolInputError("an unknown argument was supplied")
        for key, item in value.items():
            if not isinstance(key, str):
                raise ToolInputError("argument names must be strings")
            if key in properties:
                _validate(item, properties[key], depth=depth + 1)
    elif expected == "array":
        if not isinstance(value, list):
            raise ToolInputError("expected an array")
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 10**9):
            raise ToolInputError("array length is outside the allowed range")
        if schema.get("uniqueItems"):
            fingerprints = [_unique_fingerprint(item) for item in value]
            if len(fingerprints) != len(set(fingerprints)):
                raise ToolInputError("array entries must be unique")
        item_schema = schema.get("items")
        if item_schema:
            for item in value:
                _validate(item, item_schema, depth=depth + 1)
    elif expected == "string":
        if not isinstance(value, str):
            raise ToolInputError("expected a string")
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 10**9):
            raise ToolInputError("string length is outside the allowed range")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            raise ToolInputError("string does not match the required pattern")
    elif expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ToolInputError("expected an integer")
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            raise ToolInputError("integer is outside the allowed range")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolInputError("value is outside the allowed set")
