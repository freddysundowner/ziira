"""Less noise: grouping, putting a finding aside, "this is normal" rules, topics, and who may do what."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.stock_helpers import make_stock_shop, system
from ziira.kernel import extensions
from ziira.modules.intel.public import INTEL_CHECK, Candidate, CheckContext, IntelCheck, Record
from ziira.modules.intel.services import engine

INTEL = "/api/v1/intel"
PLAN: dict[str, Any] = {"items": []}


class NoiseCheck(IntelCheck):
    code = "test.noise"
    title = "A noisy check"
    area = "cash_sales"
    description = "For tests"
    params = {"limit": "100"}
    auto_resolves = False

    def run(self, session, ctx: CheckContext) -> list[Candidate]:  # type: ignore[no-untyped-def]
        return [make(ctx.company_id, *item) for item in PLAN["items"]]


def make(company_id: UUID, fp: str, severity: str, branch: UUID | None, amount: str, who: UUID | None = None) -> Candidate:
    return Candidate(
        fingerprint=fp, severity=severity, summary=f"Noise {fp}", recommended_action="Look", company_id=company_id,
        branch_id=branch, amount=Decimal(amount), value=Decimal(amount), entity_type="kernel.app_user" if who else None,
        entity_id=who, records=(Record("kernel.app_user", who, "Mary W"),) if who else (), figures={"total": amount})


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    import ziira.modules.intel.hooks  # noqa: F401

    point = extensions._points[INTEL_CHECK]
    extensions._add_implementation(point, "intel", NoiseCheck)
    s = make_stock_shop(client, registry, "Noise Co")
    registry.enable(s["tenant_id"], "intel")
    yield s
    point.implementations.remove(("intel", NoiseCheck))


def run(shop) -> Any:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return engine.run_company(s, shop["company_id"], today=date(2026, 10, 14), only={"test.noise"})


def mine(client, shop, **params) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    r = client.get(f"{INTEL}/findings", headers=shop["owner"], params={"check_code": "test.noise", **params})
    assert r.status_code == 200, r.text
    return [f for f in r.json() if f["summary"].startswith("Noise")]


def one(client, shop, fp: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return next(f for f in mine(client, shop, view="open") + mine(client, shop, status="resolved", snoozed="include")
                if f["summary"] == f"Noise {fp}")


def test_similar_findings_are_one_card_with_a_count_and_the_findings_are_unchanged(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["items"] = [("g1", "medium", shop["branch_id"], "10"), ("g2", "high", shop["branch_id"], "30"),
                     ("g3", "medium", shop["juja"], "500")]
    run(shop)
    r = client.get(f"{INTEL}/findings/grouped", headers=shop["owner"], params={"check_code": "test.noise"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["total_groups"], body["total_findings"], body["urgent_groups"]) == (2, 3, 1)
    first, second = body["groups"]
    assert first["count"] == 2 and first["severity"] == "high" and Decimal(first["amount"]) == 40     # urgency first
    assert [m["summary"] for m in first["members"]] == ["Noise g2", "Noise g1"] and second["count"] == 1
    assert len(mine(client, shop)) == 3                       # the list itself still shows every finding
    capped = client.get(f"{INTEL}/findings/grouped", headers=shop["owner"], params={"check_code": "test.noise", "limit": 1})
    assert len(capped.json()["groups"]) == 1 and capped.json()["total_groups"] == 2


def test_a_finding_put_aside_is_hidden_until_it_gets_worse(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["items"] = [("z1", "low", shop["branch_id"], "10")]
    run(shop)
    f = one(client, shop, "z1")
    r = client.post(f"{INTEL}/findings/{f['id']}/snooze", headers=shop["owner"], json={"days": 3})
    assert r.status_code == 200 and r.json()["snoozed_until"]
    assert "Noise z1" not in {x["summary"] for x in mine(client, shop)}
    assert "Noise z1" not in {m["summary"] for g in client.get(f"{INTEL}/findings/grouped", headers=shop["owner"]).json()["groups"] for m in g["members"]}
    assert "Noise z1" in {x["summary"] for x in mine(client, shop, view="waiting")}
    assert client.get(f"{INTEL}/findings/summary", headers=shop["owner"]).json()["snoozed"] >= 1
    run(shop)                                                  # same problem, not worse: still put aside
    assert "Noise z1" not in {x["summary"] for x in mine(client, shop)}
    PLAN["items"] = [("z1", "high", shop["branch_id"], "10")]
    run(shop)                                                  # worse: back
    assert "Noise z1" in {x["summary"] for x in mine(client, shop)}
    events = [e["event"] for e in client.get(f"{INTEL}/findings/{f['id']}", headers=shop["owner"]).json()["events"]]
    assert "snoozed" in events


def test_snoozing_needs_a_sensible_number_of_days_and_can_be_undone(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["items"] = [("z2", "low", shop["branch_id"], "10")]
    run(shop)
    f = one(client, shop, "z2")
    assert client.post(f"{INTEL}/findings/{f['id']}/snooze", headers=shop["owner"], json={"days": 500}).status_code == 422
    client.post(f"{INTEL}/findings/{f['id']}/snooze", headers=shop["owner"], json={"days": 7})
    back = client.post(f"{INTEL}/findings/{f['id']}/snooze", headers=shop["owner"], json={"days": None})
    assert back.status_code == 200 and back.json()["snoozed_until"] is None


def test_this_is_normal_for_a_branch_stops_it_being_raised_and_closes_the_others(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["items"] = [("n1", "medium", shop["juja"], "10"), ("n2", "medium", shop["juja"], "20"),
                     ("n3", "medium", shop["branch_id"], "30")]
    run(shop)
    f = one(client, shop, "n1")
    opts = client.get(f"{INTEL}/findings/{f['id']}/ignore-options", headers=shop["owner"]).json()
    assert opts["branch"]["name"] and opts["subject"] is None
    r = client.post(f"{INTEL}/findings/{f['id']}/ignore", headers=shop["owner"], json={"scope": "branch", "days": 30})
    assert r.status_code == 200, r.text
    assert r.json()["closed"] >= 1 and r.json()["finding"]["status"] == "dismissed"
    assert client.post(f"{INTEL}/findings/{f['id']}/ignore", headers=shop["owner"], json={"scope": "person"}).status_code in (409, 422)
    live = {x["summary"] for x in mine(client, shop)}
    assert "Noise n2" not in live and "Noise n3" in live                 # the other branch is untouched
    PLAN["items"] += [("n4", "high", shop["juja"], "99"), ("n5", "high", shop["branch_id"], "99")]
    run(shop)
    live = {x["summary"] for x in mine(client, shop)}
    assert "Noise n4" not in live and "Noise n5" in live                 # new ones at that branch are not raised
    rules = client.get(f"{INTEL}/ignore-rules", headers=shop["owner"]).json()
    rule = next(x for x in rules if x["check_code"] == "test.noise")
    assert rule["until_date"] and rule["scope_label"]
    assert client.delete(f"{INTEL}/ignore-rules/{rule['id']}", headers=shop["owner"]).status_code == 204
    run(shop)
    assert "Noise n4" in {x["summary"] for x in mine(client, shop)}      # the rule is gone: raised again
    with system(shop) as s:
        audited = s.execute(text("select count(*) from kernel.audit_log where action in "
                                 "('finding.ignore_rule', 'finding.ignore_rule_removed')")).scalar()
    assert audited >= 2


def test_this_is_normal_for_a_person_forever(client, shop) -> None:  # type: ignore[no-untyped-def]
    mary = uuid4()
    PLAN["items"] = [("p1", "medium", shop["branch_id"], "10", mary), ("p2", "medium", shop["juja"], "20", mary),
                     ("p3", "medium", shop["juja"], "20", uuid4())]
    run(shop)
    f = one(client, shop, "p1")
    related = client.get(f"{INTEL}/findings/{f['id']}/related", headers=shop["owner"]).json()
    assert "Noise p2" in {x["summary"] for x in related} and "Noise p3" not in {x["summary"] for x in related}   # same person yes; another person elsewhere no
    opts = client.get(f"{INTEL}/findings/{f['id']}/ignore-options", headers=shop["owner"]).json()
    assert opts["subject"]["label"] == "Mary W" and opts["subject"]["kind"] == "person"
    r = client.post(f"{INTEL}/findings/{f['id']}/ignore", headers=shop["owner"], json={"scope": "person", "days": None})
    assert r.status_code == 200 and r.json()["closed"] == 1
    live = {x["summary"] for x in mine(client, shop)}
    assert "Noise p2" not in live and "Noise p3" in live
    rule = next(x for x in client.get(f"{INTEL}/ignore-rules", headers=shop["owner"]).json() if x["entity_type"])
    assert rule["until_date"] is None


def test_only_people_who_manage_findings_can_ignore_or_see_the_rules(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["items"] = [("m1", "medium", shop["branch_id"], "10")]
    run(shop)
    f = one(client, shop, "m1")
    assert client.post(f"{INTEL}/findings/{f['id']}/ignore", headers=shop["manager"], json={"scope": "everywhere"}).status_code == 403
    assert client.get(f"{INTEL}/ignore-rules", headers=shop["manager"]).status_code == 403
    assert client.put(f"{INTEL}/topics", headers=shop["manager"], json={"topics": {"cash": False}}).status_code == 403
    assert client.get(f"{INTEL}/findings/grouped", headers=shop["juja_keeper"]).status_code == 403
    assert client.get(f"{INTEL}/plain", headers=shop["manager"]).status_code == 200


def test_the_limit_is_raised_only_for_checks_that_allow_it(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["items"] = [("t1", "medium", shop["branch_id"], "10")]
    run(shop)
    f = one(client, shop, "t1")
    r = client.post(f"{INTEL}/findings/{f['id']}/ignore", headers=shop["owner"], json={"scope": "everywhere", "days": 1, "tune": True})
    assert r.status_code == 200 and r.json()["tuned"] is None            # test.noise is not a tunable check


def test_topics_switch_whole_groups_of_checks(client, shop) -> None:  # type: ignore[no-untyped-def]
    before = client.get(f"{INTEL}/topics", headers=shop["owner"]).json()
    assert {t["key"] for t in before["topics"]} == {"cash", "stock", "customers", "suppliers", "staff", "books"}
    r = client.put(f"{INTEL}/topics", headers=shop["owner"], json={"topics": {"stock": False}})
    assert r.status_code == 200 and r.json()["configured"] is True
    stock = next(t for t in r.json()["topics"] if t["key"] == "stock")
    assert stock["checks"] > 0 and stock["enabled"] == 0
    checks = client.get(f"{INTEL}/checks", headers=shop["owner"]).json()
    assert all(not c["enabled"] for c in checks if c["topic"] == "stock")
    client.put(f"{INTEL}/topics", headers=shop["owner"], json={"topics": {"stock": True}})
    assert client.put(f"{INTEL}/topics", headers=shop["owner"], json={"topics": {"nope": True}}).status_code == 422


def test_a_check_can_be_reset_to_the_recommended_setting(client, shop) -> None:  # type: ignore[no-untyped-def]
    client.patch(f"{INTEL}/checks/test.noise", headers=shop["owner"], json={"enabled": False, "params": {"limit": "7"}})
    r = client.post(f"{INTEL}/checks/test.noise/reset", headers=shop["owner"])
    assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["params"]["limit"] == "100"


def test_the_plain_words_come_in_both_languages(client, shop) -> None:  # type: ignore[no-untyped-def]
    en = client.get(f"{INTEL}/plain", headers=shop["owner"]).json()
    sw = client.get(f"{INTEL}/plain", params={"lang": "sw"}, headers=shop["owner"]).json()
    assert en["checks"]["controls.exceptions_backlog"]["title"] != sw["checks"]["controls.exceptions_backlog"]["title"]
    assert en["checks"]["test.noise"]["fallback"] is True               # a check with no text falls back to its own title
    assert set(en["figures"]) == set(sw["figures"]) and en["params"]["days"]
