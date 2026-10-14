"""A change is committed before the client is told it worked.

FastAPI ends `yield` dependencies after the response has been sent unless their scope is "function"; the database
session must end (and commit) first, so that the next request sees the change and a failed commit is an error reply.
"""

from tests.conftest import make_tenant, sign_in


def test_what_a_create_reply_promises_is_already_committed(client, registry) -> None:  # type: ignore[no-untyped-def]
    t = make_tenant("Commit Co")
    registry.enable(t["tenant_id"], "products")
    code = "commit-co"
    h = sign_in(client, code, f"owner@{code}.test").headers
    for i in range(40):                                                    # a race shows up as a miss, not every time
        made = client.post("/api/v1/products/uoms", headers=h, json={"code": f"U{i:02d}"[:3].replace("0", "A"),
                                                                      "name": f"Unit {i}"})
        if made.status_code != 201:
            continue                                                       # codes repeat after a few: duplicates are fine
        listed = {u["id"] for u in client.get("/api/v1/products/uoms", headers=h).json()}
        assert made.json()["id"] in listed, f"unit {i} was not visible right after its 201"


def test_the_session_dependency_ends_before_the_response() -> None:
    from ziira.sdk import DB_SESSION

    assert DB_SESSION.dependency is not None and DB_SESSION.scope == "function"
