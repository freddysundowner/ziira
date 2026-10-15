"""Checking what the model sent a tool against the tool's JSON schema (the small subset tools use)."""

from datetime import date
from typing import Any


class BadParams(ValueError):
    """The model's arguments do not fit the tool's schema; the message goes back to the model."""


def check_params(schema: dict[str, Any], arguments: Any) -> dict[str, Any]:
    """The arguments the schema allows, cleaned: unknown keys are dropped, types and bounds are enforced, strings
    marked `format: date` must be ISO dates. Raises BadParams."""
    if not isinstance(arguments, dict):
        raise BadParams("The arguments must be an object")
    properties: dict[str, Any] = schema.get("properties", {})
    out: dict[str, Any] = {}
    for name, spec in properties.items():
        if name not in arguments or arguments[name] is None:
            continue
        out[name] = _one(name, spec, arguments[name])
    missing = [r for r in schema.get("required", []) if r not in out]
    if missing:
        raise BadParams(f"Missing: {', '.join(missing)}")
    return out


def _one(name: str, spec: dict[str, Any], value: Any) -> Any:
    kind = spec.get("type")
    if kind == "string":
        if not isinstance(value, str):
            raise BadParams(f"{name} must be text")
        value = value.strip()[: int(spec.get("maxLength", 200))]
        if spec.get("format") == "date":
            try:
                date.fromisoformat(value)
            except ValueError:
                raise BadParams(f"{name} must be a date written YYYY-MM-DD") from None
        if spec.get("format") == "uuid":
            from uuid import UUID

            try:
                UUID(value)
            except ValueError:
                raise BadParams(f"{name} must be an id from the list you were given") from None
        if "enum" in spec and value not in spec["enum"]:
            raise BadParams(f"{name} must be one of: {', '.join(spec['enum'])}")
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise BadParams(f"{name} must be a whole number")
        low, high = spec.get("minimum"), spec.get("maximum")
        if (low is not None and value < low) or (high is not None and value > high):
            raise BadParams(f"{name} must be between {low} and {high}")
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            raise BadParams(f"{name} must be true or false")
        return value
    raise BadParams(f"{name} has an unsupported type")  # pragma: no cover - a tool author's mistake
