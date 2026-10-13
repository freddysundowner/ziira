"""A small schema-driven fuzzer: builds a valid request for every endpoint from the OpenAPI description and
then changes one value at a time to something hostile. The rule it checks: no input may cause a server error
(HTTP 5xx or an exception escaping the application)."""

import copy
import random
import uuid
from collections.abc import Callable, Iterator
from typing import Any

HOSTILE: dict[str, list[Any]] = {
    "string": ["", " ", "\x00", "a\x00b", "x" * 5000, "'; drop table kernel.app_user; --", "💥🇰🇪 ünïcödé", "‮", "null",
               "../../etc/passwd", "<script>alert(1)</script>", "%s%n", "0", "-1", "1e400", "NaN", "Infinity"],
    "integer": [0, -1, 1, 2**31, 2**63, -(2**63), 10**30, 1.5, "1", "abc", None, True],
    "number": ["NaN", "Infinity", "-Infinity", "1e400", "-1e400", "1e-400", "0.00000000001", "99999999999999999999",
               -1, 0, 10**30, None, True, "abc", "-0"],
    "boolean": ["yes", 2, "true", None, [], {}],
    "array": [[], [None], [[]], [{}], list(range(300)), None, "x", {}],
    "object": [{}, None, [], "x", {"a": {"b": {"c": {}}}}],
    "uuid": [str(uuid.uuid4()), "not-a-uuid", "", "0" * 36, "00000000-0000-0000-0000-000000000000", None, 7],
    "date": ["", "2026-13-45", "0000-00-00", "9999-12-31", "1900-01-01", "yesterday", None, 20260101],
    "date-time": ["", "2026-13-45T25:61:61Z", "9999-12-31T23:59:59Z", "yesterday", None],
}


class Spec:
    def __init__(self, document: dict[str, Any], ids: dict[str, str]) -> None:
        self.doc = document
        self.ids = ids

    def ref(self, node: dict[str, Any]) -> dict[str, Any]:
        while "$ref" in node:
            node = self.doc["components"]["schemas"][node["$ref"].split("/")[-1]]
        return node

    def kind(self, node: dict[str, Any]) -> str:
        node = self.ref(node)
        if "anyOf" in node:
            options = [o for o in node["anyOf"] if o.get("type") != "null"]
            return self.kind(options[0]) if options else "string"
        if node.get("format") == "uuid":
            return "uuid"
        if node.get("format") in ("date", "date-time"):
            return node["format"]
        if node.get("type") in HOSTILE:
            return str(node["type"])
        if "properties" in node:
            return "object"
        return "string"

    def sample(self, node: dict[str, Any], name: str = "") -> Any:
        node = self.ref(node)
        if "anyOf" in node:
            options = [o for o in node["anyOf"] if o.get("type") != "null"]
            return self.sample(options[0], name) if options else None
        if "enum" in node:
            return node["enum"][0]
        if "const" in node:
            return node["const"]
        kind = self.kind(node)
        if kind == "uuid":
            return self.ids.get(name) or self.ids.get(name.removesuffix("_id") + "_id") or str(uuid.uuid4())
        if kind == "date":
            return "2026-10-13"
        if kind == "date-time":
            return "2026-10-13T10:00:00Z"
        if kind == "integer":
            return max(node.get("minimum", 1), 1)
        if kind == "number":
            if node.get("type") == "string":
                return "1"
            return max(node.get("exclusiveMinimum", 0) + 1, node.get("minimum", 1), 1)
        if kind == "boolean":
            return True
        if kind == "array":
            return [self.sample(node.get("items", {}), name)]
        if kind == "object":
            return {key: self.sample(value, key) for key, value in node.get("properties", {}).items()
                    if key in node.get("required", []) or True}
        text = node.get("examples", [None])[0] if node.get("examples") else None
        if "decimal" in str(node.get("pattern", "")) or node.get("type") == "string" and "pattern" in node:
            return "1"
        return text if isinstance(text, str) else "x"


def operations(spec: Spec, skip: tuple[str, ...]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    for path, methods in spec.doc["paths"].items():
        if any(s in path for s in skip):
            continue
        for method, operation in methods.items():
            if method in ("get", "post", "put", "patch", "delete"):
                yield method.upper(), path, operation


def build(spec: Spec, path: str, operation: dict[str, Any]) -> tuple[str, dict[str, Any], Any]:
    """A valid URL, query parameters and body for the operation."""
    query: dict[str, Any] = {}
    for parameter in operation.get("parameters", []):
        value = spec.sample(parameter["schema"], parameter["name"])
        if parameter["in"] == "path":
            path = path.replace("{" + parameter["name"] + "}", str(value))
        elif parameter["in"] == "query" and parameter.get("required"):
            query[parameter["name"]] = value
    body = None
    content = operation.get("requestBody", {}).get("content", {}).get("application/json")
    if content:
        body = spec.sample(content["schema"])
    return path, query, body


def mutations(spec: Spec, method: str, path: str, operation: dict[str, Any], rng: random.Random, per_field: int,
              fix: Callable[[str, str, Any], Any] | None = None) -> Iterator[tuple[str, dict[str, Any], Any, str]]:
    """Requests with one thing changed: a path/query parameter, or one body field (at any depth).

    `fix(method, path, body)` may replace the generated body with one that is valid for the business rules.
    """
    base_path, base_query, base_body = build(spec, path, operation)
    if fix is not None:
        base_body = fix(method, path, base_body)
    yield base_path, base_query, base_body, "baseline"
    for parameter in operation.get("parameters", []):
        kind = spec.kind(parameter["schema"])
        for value in rng.sample(HOSTILE.get(kind, HOSTILE["string"]), min(per_field, len(HOSTILE.get(kind, [])))):
            if parameter["in"] == "path":
                yield path.replace("{" + parameter["name"] + "}", str(value)), base_query, base_body, \
                    f"path {parameter['name']}={value!r}"
            else:
                yield base_path, {**base_query, parameter["name"]: value}, base_body, \
                    f"query {parameter['name']}={value!r}"
    if isinstance(base_body, (dict, list)):
        for location in leaves(base_body):
            kind = spec.kind_at(operation, location) if hasattr(spec, "kind_at") else guess_kind(base_body, location)
            for value in rng.sample(HOSTILE[kind], min(per_field, len(HOSTILE[kind]))):
                changed = copy.deepcopy(base_body)
                set_at(changed, location, value)
                yield base_path, base_query, changed, f"body {'.'.join(map(str, location))}={value!r}"
            changed = copy.deepcopy(base_body)
            if len(location) and isinstance(get_parent(changed, location), dict):
                del get_parent(changed, location)[location[-1]]
                yield base_path, base_query, changed, f"body without {'.'.join(map(str, location))}"
    if isinstance(base_body, dict):
        yield base_path, base_query, {**base_body, "unexpected": {"x": 1}}, "unknown field"
        yield base_path, base_query, [], "wrong body type"
        yield base_path, base_query, "text", "string body"


def leaves(node: Any, prefix: tuple = ()) -> Iterator[tuple]:  # type: ignore[type-arg]
    if isinstance(node, dict):
        for key, value in node.items():
            yield from leaves(value, (*prefix, key))
    elif isinstance(node, list):
        for index, value in enumerate(node[:1]):
            yield from leaves(value, (*prefix, index))
    else:
        yield prefix


def get_parent(root: Any, location: tuple) -> Any:  # type: ignore[type-arg]
    for part in location[:-1]:
        root = root[part]
    return root


def set_at(root: Any, location: tuple, value: Any) -> None:  # type: ignore[type-arg]
    get_parent(root, location)[location[-1]] = value


def guess_kind(body: Any, location: tuple) -> str:  # type: ignore[type-arg]
    value = body
    for part in location:
        value = value[part]
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, str):
        if len(value) == 36 and value.count("-") == 4:
            return "uuid"
        if value[:4] == "2026" and len(value) == 10:
            return "date"
        if value == "1":
            return "number"
        return "string"
    return "string"
