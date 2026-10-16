"""The public API subset: its list is real, tagged, published on its own, and deprecations are announced."""

from datetime import date
from email.utils import parsedate_to_datetime
from uuid import uuid4

from ziira.kernel import public_api


def test_every_public_endpoint_exists_and_is_tagged_public(client) -> None:  # type: ignore[no-untyped-def]
    schema = client.get("/openapi.json").json()
    for method, path in public_api.PUBLIC_ENDPOINTS:
        assert method.lower() in schema["paths"].get(path, {}), f"{method} {path} is not an endpoint"
    tagged = {(m.upper(), p) for p, ops in schema["paths"].items() for m, op in ops.items()
              if public_api.PUBLIC_TAG in op.get("tags", [])}
    assert tagged == set(public_api.PUBLIC_ENDPOINTS)


def test_public_endpoints_all_need_a_sign_in(client) -> None:  # type: ignore[no-untyped-def]
    for method, path in public_api.PUBLIC_ENDPOINTS:
        url = path.replace("{", "").replace("}", "")
        for part in [p for p in path.split("/") if p.startswith("{")]:
            url = path.replace(part, str(uuid4()))
        assert client.request(method, url, json={} if method == "POST" else None).status_code == 401, (method, path)


def test_the_public_description_stands_on_its_own(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/v1/public/openapi.json")                       # needs no sign-in: it is documentation
    assert r.status_code == 200
    doc = r.json()
    assert doc["info"]["version"] == "v1" and doc["tags"] == [{"name": "Public"}]
    assert {(m.upper(), p) for p, ops in doc["paths"].items() for m in ops} == set(public_api.PUBLIC_ENDPOINTS)
    wanted = public_api._refs(doc["paths"])
    have = set(doc["components"]["schemas"])
    assert wanted <= have                                                # every $ref resolves
    assert have == _closure(doc, wanted)                                 # and nothing else comes along
    assert "SignInIn" not in have and "/api/v1/users" not in doc["paths"]


def _closure(doc, start):  # type: ignore[no-untyped-def]
    seen, todo = set(), set(start)
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo |= public_api._refs(doc["components"]["schemas"][name])
    return seen


def test_requests_are_matched_on_their_real_paths() -> None:
    sale = str(uuid4())
    assert public_api.is_public("GET", f"/api/v1/pos/sales/{sale}")
    assert public_api.is_public("HEAD", f"/api/v1/pos/sales/{sale}")
    assert public_api.is_public("GET", f"/api/v1/pos/sales/{sale}/")
    assert not public_api.is_public("GET", f"/api/v1/pos/sales/{sale}/receipt")
    assert not public_api.is_public("DELETE", f"/api/v1/pos/sales/{sale}")
    assert not public_api.is_public("POST", "/api/v1/pos/sales")                    # selling is not in the public API
    assert not public_api.is_public("GET", "/api/v1/pos/sales/a/b")
    assert not public_api.is_public("GET", "/api/v2/pos/sales")


def test_responses_carry_the_api_version_and_deprecations_are_announced(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/v1/public/openapi.json").headers["ziira-api-version"] == "1"
    assert "ziira-api-version" not in client.get("/health").headers
    monkeypatch.setitem(public_api.DEPRECATIONS, ("GET", "/api/v1/public/openapi.json"),
                        public_api.Deprecation(date(2027, 1, 1), date(2027, 7, 1), "https://docs.example/migrate"))
    r = client.get("/api/v1/public/openapi.json")
    assert r.headers["deprecation"] == "@1798761600"                                  # 2027-01-01T00:00:00Z
    assert parsedate_to_datetime(r.headers["sunset"]).date() == date(2027, 7, 1)
    assert r.headers["link"] == '<https://docs.example/migrate>; rel="deprecation"'
    assert "deprecation" not in client.get("/api/v1/units").headers
