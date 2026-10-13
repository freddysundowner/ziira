"""Kernel services used by every module: numbering, reason codes, approvals and the outbox."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.conftest import make_tenant, sign_in

WS = "services-co"
OWNER = "owner@services-co.test"


@pytest.fixture(scope="module")
def t(client, registry):  # type: ignore[no-untyped-def]
    tenant = make_tenant("Services Co")
    registry.enable(tenant["tenant_id"], "inventory")       # also enables products
    return tenant


def system(tenant):  # type: ignore[no-untyped-def]
    """A system transaction for the tenant."""
    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session

    system_context(tenant["tenant_id"])
    return tenant_session(tenant["tenant_id"])


# --------------------------------------------------------------------------- numbering
def test_numbers_are_sequential_per_branch_and_type(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import next_document_number

    def take(branch, doc_type="stock_adjustment", prefix="ADJ") -> str:  # type: ignore[no-untyped-def]
        with system(t) as s:
            return next_document_number(s, company_id=t["company_id"], branch_id=branch, doc_type=doc_type,
                                        prefix=prefix)

    assert [take(t["branch_id"]) for _ in range(3)] == ["ADJ-HQ-000001", "ADJ-HQ-000002", "ADJ-HQ-000003"]
    assert take(None) == "ADJ-000001"                           # company-level series
    assert take(None) == "ADJ-000002"
    assert take(t["branch_id"], "transfer", "TRF") == "TRF-HQ-000001"


def test_rolled_back_transaction_gives_its_number_back(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import next_document_number

    def take() -> str:
        with system(t) as s:
            return next_document_number(s, company_id=t["company_id"], branch_id=t["branch_id"],
                                        doc_type="count", prefix="CNT")

    first = take()
    with pytest.raises(RuntimeError), system(t) as s:
        next_document_number(s, company_id=t["company_id"], branch_id=t["branch_id"], doc_type="count", prefix="CNT")
        raise RuntimeError("the document failed to save")
    assert take() == first.replace("000001", "000002")


def test_series_can_be_renamed_but_not_moved_back(client, t) -> None:  # type: ignore[no-untyped-def]
    owner = sign_in(client, WS, OWNER).headers
    series = {x["doc_type"] + str(x["branch_id"]): x for x in
              client.get("/api/v1/settings/document-series", headers=owner).json()}
    adj = series["stock_adjustment" + str(t["branch_id"])]
    r = client.patch(f"/api/v1/settings/document-series/{adj['id']}", headers=owner, json={"next_number": 1})
    assert r.status_code == 422
    r = client.patch(f"/api/v1/settings/document-series/{adj['id']}", headers=owner,
                     json={"prefix": "SA-HQ-2026-", "padding": 4})
    assert r.status_code == 200
    from ziira.sdk import next_document_number

    with system(t) as s:
        n = next_document_number(s, company_id=t["company_id"], branch_id=t["branch_id"],
                                 doc_type="stock_adjustment", prefix="ADJ")
    assert n == "SA-HQ-2026-0004"


# --------------------------------------------------------------------------- reason codes
def test_enabling_a_unit_seeds_its_reason_codes(client, t) -> None:  # type: ignore[no-untyped-def]
    owner = sign_in(client, WS, OWNER).headers
    codes = client.get("/api/v1/settings/reason-codes?category=stock_adjustment", headers=owner).json()
    assert {"DAMAGED", "EXPIRED", "THEFT", "FOUND", "DATA_ERROR"} == {c["code"] for c in codes}


def test_reason_checks(client, t) -> None:  # type: ignore[no-untyped-def]
    from ziira.sdk import ValidationFailed, check_reason

    owner = sign_in(client, WS, OWNER).headers
    r = client.post("/api/v1/settings/reason-codes", headers=owner,
                    json={"category": "stock_adjustment", "code": "other", "label": "Other", "requires_note": True})
    assert r.status_code == 201 and r.json()["code"] == "OTHER"
    other = r.json()["id"]
    assert client.post("/api/v1/settings/reason-codes", headers=owner,
                       json={"category": "stock_adjustment", "code": "OTHER", "label": "x"}).status_code == 409
    assert client.post("/api/v1/settings/reason-codes", headers=owner,
                       json={"category": "nonsense", "code": "X", "label": "x"}).status_code == 422
    write_off = client.get("/api/v1/settings/reason-codes?category=write_off", headers=owner).json()[0]["id"]

    with system(t) as s:
        check_reason(s, "stock_adjustment", other, "Rats got into the store")
        for args, message in (((None,), "required"), ((write_off,), "Choose a reason"),
                              ((other,), "needs a note"), ((other, "  "), "needs a note")):
            with pytest.raises(ValidationFailed, match=message):
                check_reason(s, "stock_adjustment", *args)

    assert client.post(f"/api/v1/settings/reason-codes/{other}/active", headers=owner,
                       json={"active": False}).status_code == 204
    with system(t) as s, pytest.raises(ValidationFailed, match="no longer in use"):
        check_reason(s, "stock_adjustment", other, "note")
    listed = client.get("/api/v1/settings/reason-codes?category=stock_adjustment", headers=owner).json()
    assert other not in {c["id"] for c in listed}


# --------------------------------------------------------------------------- approvals
@pytest.fixture(scope="module")
def people(client, t):  # type: ignore[no-untyped-def]
    """A storekeeper who submits, two branch managers and a finance manager who approve."""
    owner = sign_in(client, WS, OWNER).headers
    roles = {r["name"]: r["id"] for r in client.get("/api/v1/roles", headers=owner).json()}
    out = {"owner": owner, "roles": roles}
    for name, role in (("store", "Storekeeper"), ("mgr1", "Branch Manager"), ("mgr2", "Branch Manager"),
                       ("fin", "Finance Manager")):
        u = client.post("/api/v1/users", headers=owner, json={"full_name": name, "email": f"{name}@services-co.test",
                                                              "password": f"{name}-pass-12"}).json()
        r = client.post(f"/api/v1/users/{u['id']}/roles", headers=owner,
                        json={"role_id": roles[role], "scope": "company", "company_id": str(t["company_id"])})
        assert r.status_code == 201, r.text
        out[name] = sign_in(client, WS, f"{name}@services-co.test", f"{name}-pass-12").headers
        out[name + "_id"] = u["id"]
    # Matrix: every adjustment needs a branch manager; above 50,000 the finance manager approves next.
    for step, minimum, role in ((1, "0", "Branch Manager"), (2, "50000", "Finance Manager")):
        r = client.post("/api/v1/approvals/rules", headers=owner,
                        json={"company_id": str(t["company_id"]), "doc_type": "stock_adjustment", "step": step,
                              "min_amount": minimum, "approver_role_id": roles[role]})
        assert r.status_code == 201, r.text
    return out


def submit_as(t, user_id: str, amount: str, doc_type: str = "stock_adjustment"):  # type: ignore[no-untyped-def]
    """Submit a document for approval as `user_id`; returns (doc_id, status)."""
    from ziira.kernel.context import RequestContext, set_context
    from ziira.kernel.db import tenant_session
    from ziira.sdk import submit_for_approval

    doc_id = uuid4()
    set_context(RequestContext(tenant_id=t["tenant_id"], user_id=UUID(user_id)))
    with tenant_session(t["tenant_id"]) as s:
        status = submit_for_approval(s, company_id=t["company_id"], doc_type=doc_type, doc_id=doc_id,
                                     amount=Decimal(amount))
    return doc_id, status


def pending(client, headers, doc_id) -> list[dict]:  # type: ignore[no-untyped-def,type-arg]
    return [r for r in client.get("/api/v1/approvals/pending", headers=headers).json() if r["doc_id"] == str(doc_id)]


def decided_events(t, doc_id) -> list[dict]:  # type: ignore[no-untyped-def,type-arg]
    with system(t) as s:
        return [r.payload for r in s.execute(text(
            "select payload from kernel.event_outbox where event_type = 'approval.decided' and aggregate_id = :i"),
            {"i": str(doc_id)})]


def test_no_matching_rule_means_no_approval_needed(t, people) -> None:  # type: ignore[no-untyped-def]
    _, status = submit_as(t, people["store_id"], "100", doc_type="transfer")
    assert status == "approved"


def test_single_step_approval(client, t, people) -> None:  # type: ignore[no-untyped-def]
    doc_id, status = submit_as(t, people["store_id"], "1200")
    assert status == "pending"
    assert pending(client, people["fin"], doc_id) == []            # not their step
    [request] = pending(client, people["mgr1"], doc_id)
    # The storekeeper holds no approver role
    r = client.post(f"/api/v1/approvals/{request['id']}/decision", headers=people["store"], json={"approve": True})
    assert r.status_code == 403
    r = client.post(f"/api/v1/approvals/{request['id']}/decision", headers=people["mgr1"], json={"approve": True})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    [event] = decided_events(t, doc_id)
    assert event["status"] == "approved" and event["decided_by"] == people["mgr1_id"]
    # Cannot decide twice
    r = client.post(f"/api/v1/approvals/{request['id']}/decision", headers=people["mgr2"], json={"approve": True})
    assert r.status_code == 409


def test_large_amount_needs_two_steps(client, t, people) -> None:  # type: ignore[no-untyped-def]
    doc_id, _ = submit_as(t, people["store_id"], "75000")
    [step1] = pending(client, people["mgr1"], doc_id)
    client.post(f"/api/v1/approvals/{step1['id']}/decision", headers=people["mgr1"], json={"approve": True})
    assert decided_events(t, doc_id) == []                         # not finished yet
    [step2] = pending(client, people["fin"], doc_id)
    assert step2["step"] == 2 and step2["requested_by"] == people["store_id"]
    assert pending(client, people["mgr2"], doc_id) == []
    r = client.post(f"/api/v1/approvals/{step2['id']}/decision", headers=people["fin"], json={"approve": True})
    assert r.status_code == 200
    assert [e["status"] for e in decided_events(t, doc_id)] == ["approved"]


def test_creator_cannot_approve_their_own_request(client, t, people) -> None:  # type: ignore[no-untyped-def]
    doc_id, _ = submit_as(t, people["mgr1_id"], "500")
    [request] = pending(client, people["mgr1"], doc_id)
    r = client.post(f"/api/v1/approvals/{request['id']}/decision", headers=people["mgr1"], json={"approve": True})
    assert r.status_code == 403 and "separation of duties" in r.json()["message"]
    r = client.post(f"/api/v1/approvals/{request['id']}/decision", headers=people["mgr2"], json={"approve": True})
    assert r.status_code == 200


def test_rejection_needs_a_reason_and_ends_the_request(client, t, people) -> None:  # type: ignore[no-untyped-def]
    doc_id, _ = submit_as(t, people["store_id"], "75000")
    [request] = pending(client, people["mgr1"], doc_id)
    url = f"/api/v1/approvals/{request['id']}/decision"
    assert client.post(url, headers=people["mgr1"], json={"approve": False}).status_code == 422
    r = client.post(url, headers=people["mgr1"], json={"approve": False, "note": "Count it again"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert [e["status"] for e in decided_events(t, doc_id)] == ["rejected"]
    assert pending(client, people["fin"], doc_id) == []            # no second step after a rejection


def test_document_cannot_be_submitted_twice_while_pending(t, people) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.context import RequestContext, set_context
    from ziira.kernel.db import tenant_session
    from ziira.sdk import Conflict, submit_for_approval

    doc_id, _ = submit_as(t, people["store_id"], "10")
    set_context(RequestContext(tenant_id=t["tenant_id"], user_id=UUID(people["store_id"])))
    with pytest.raises(Conflict), tenant_session(t["tenant_id"]) as s:
        submit_for_approval(s, company_id=t["company_id"], doc_type="stock_adjustment", doc_id=doc_id)


def test_only_company_approvers_manage_rules(client, t, people) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/approvals/rules", headers=people["mgr1"],
                    json={"company_id": str(t["company_id"]), "doc_type": "x",
                          "approver_role_id": people["roles"]["Owner"]})
    assert r.status_code == 403


# --------------------------------------------------------------------------- outbox
def test_outbox_delivers_after_commit_and_retries_failures(t) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import events, outbox
    from ziira.sdk import Event, publish

    seen: list[str] = []
    fail = {"on": True}

    def remember(_s, event) -> None:  # type: ignore[no-untyped-def]
        seen.append(str(event.aggregate_id))

    def flaky(_s, event) -> None:  # type: ignore[no-untyped-def]
        if fail["on"]:
            raise RuntimeError("webhook down")

    # Handlers registered for the kernel (always enabled) so the test needs no unit.
    events._after_commit["test.happened"] += [("kernel", remember)]
    events._after_commit["test.flaky"] += [("kernel", flaky)]
    try:
        ok_id, flaky_id, rolled_back_id = uuid4(), uuid4(), uuid4()
        with system(t) as s:
            publish(s, Event(type="test.happened", aggregate_type="test", aggregate_id=ok_id))
            publish(s, Event(type="test.flaky", aggregate_type="test", aggregate_id=flaky_id))
            assert seen == []                              # nothing runs before commit
        with pytest.raises(RuntimeError), system(t) as s:
            publish(s, Event(type="test.happened", aggregate_type="test", aggregate_id=rolled_back_id))
            raise RuntimeError("rolled back")

        outbox.process_tenant(t["tenant_id"])
        assert seen == [str(ok_id)]                        # delivered once; the rolled-back event never existed

        def state(i):  # type: ignore[no-untyped-def]
            with system(t) as s:
                return s.execute(text("select published_at, attempts, last_error from kernel.event_outbox "
                                      "where aggregate_id = :i"), {"i": str(i)}).one()

        assert state(flaky_id).published_at is None
        assert state(flaky_id).attempts == 1 and "webhook down" in state(flaky_id).last_error
        outbox.process_tenant(t["tenant_id"])
        assert seen == [str(ok_id)]                        # not delivered twice
        fail["on"] = False
        outbox.process_tenant(t["tenant_id"])
        assert state(flaky_id).published_at is not None and state(flaky_id).last_error is None
    finally:
        events._after_commit.pop("test.happened", None)
        events._after_commit.pop("test.flaky", None)
