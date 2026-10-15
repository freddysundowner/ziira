"""Intelligence levels 3 and 4: proposing actions for findings, approving them, and the routine ones an owner lets run by
themselves. The checks and actions here are small fakes so the machinery is tested on its own; the real providers
(purchasing, pricing, reminders, ...) are tested with their units in `tests/test_intel_action_providers.py`."""

import inspect
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.stock_helpers import make_stock_shop, system
from ziira.kernel import extensions
from ziira.modules.intel.domain import action_rules
from ziira.modules.intel.public import (
    INTEL_ACTION,
    INTEL_CHECK,
    ActionContext,
    ActionProvider,
    ActionResult,
    Candidate,
    CheckContext,
    FindingInfo,
    IntelCheck,
    Proposal,
    Record,
)
from ziira.modules.intel.services import engine
from ziira.sdk import ValidationFailed, current_context, flag_for_review

INTEL = "/api/v1/intel"
PLAN: dict[str, Any] = {"candidates": []}
SEEN: list[dict[str, Any]] = []            # what the fake actions saw when they ran


class FakeCheck(IntelCheck):
    code = "test.act"
    title = "A check the fake actions answer"
    area = "stock"
    params: dict[str, Any] = {}

    def run(self, session, ctx: CheckContext) -> list[Candidate]:  # type: ignore[no-untyped-def]
        return [c(ctx.company_id) for c in PLAN["candidates"]]


class FakeDraft(ActionProvider):
    """Prepares a draft (an item in the exceptions inbox stands in for it). Always needs a person."""

    type = "test.draft"
    title = "Prepare a draft"
    description = "Makes a draft for a person to look at"
    check_codes = ("test.act",)
    needs_permission = "exceptions.manage"
    auto_allowed = False
    params_schema = {"properties": {
        "quantity": {"type": "number", "title": "Quantity", "minimum": "1", "maximum": "100"},
        "note": {"type": "string", "title": "Note", "max_length": 20},
        "code": {"type": "string", "title": "Code", "editable": False}}, "required": ["quantity"]}

    def proposes(self, session, finding: FindingInfo) -> list[Proposal]:  # type: ignore[no-untyped-def]
        if "nodraft" in finding.summary:
            return []
        return [Proposal(params={"quantity": "5", "code": "ABC"}, description=f"Draft for: {finding.summary}",
                         facts={"Why": "a test"})]

    def execute(self, session, context: ActionContext, params: dict[str, Any]) -> ActionResult:  # type: ignore[no-untyped-def]
        ctx = current_context()
        SEEN.append({"type": self.type, "automatic": context.automatic, "channel": ctx.channel, "user": ctx.user_id,
                     "params": dict(params)})
        if params.get("note") == "boom":
            raise ValidationFailed("The supplier is on hold")
        if params.get("note") == "crash":
            raise RuntimeError("secret internals")
        item = flag_for_review(session, unit="test", kind="draft", company_id=context.company_id,
                               message=f"Draft of {params['quantity']}", dedupe_key=f"draft:{context.proposal_id}")
        return ActionResult(True, f"Draft made ({params['quantity']})", (("test.draft", item, "Draft 1"),))


class FakeNudge(ActionProvider):
    """A routine message: may run by itself under an owner's rule."""

    type = "test.nudge"
    title = "Send a nudge"
    check_codes = ("test.act",)
    needs_permission = "findings.manage"
    auto_allowed = True
    rule_schema = {"properties": {"severity": {"type": "string", "title": "Severity", "enum": ["low", "medium", "high"]}}}

    def proposes(self, session, finding: FindingInfo) -> list[Proposal]:  # type: ignore[no-untyped-def]
        return [Proposal(params={}, description="Nudge someone", facts={})]

    def covered_by(self, conditions: dict[str, Any], params: dict[str, Any], finding: FindingInfo) -> bool:
        return conditions.get("severity") in (None, finding.severity)

    def execute(self, session, context: ActionContext, params: dict[str, Any]) -> ActionResult:  # type: ignore[no-untyped-def]
        ctx = current_context()
        SEEN.append({"type": self.type, "automatic": context.automatic, "channel": ctx.channel, "user": ctx.user_id,
                     "can_post": ctx.can("exceptions.manage", company_id=context.company_id),
                     "can_nudge": ctx.can("findings.manage", company_id=context.company_id)})
        return ActionResult(True, "Nudged")


class FakeMoney(ActionProvider):
    """Says it is automatic but needs a permission that means prices: it can never run by itself."""

    type = "test.money"
    title = "Change a price"
    check_codes = ("test.act",)
    needs_permission = "prices.manage"
    auto_allowed = True

    def proposes(self, session, finding: FindingInfo) -> list[Proposal]:  # type: ignore[no-untyped-def]
        return []

    def execute(self, session, context: ActionContext, params: dict[str, Any]) -> ActionResult:  # type: ignore[no-untyped-def]
        return ActionResult(True, "Never reached by a rule")


class FakeGreedy(ActionProvider):
    """Automatic, but tries to do something its one permission does not cover."""

    type = "test.greedy"
    title = "Greedy"
    check_codes = ("test.greedy",)
    needs_permission = "findings.manage"
    auto_allowed = True

    def proposes(self, session, finding: FindingInfo) -> list[Proposal]:  # type: ignore[no-untyped-def]
        return [Proposal(params={}, description="Greedy")]

    def execute(self, session, context: ActionContext, params: dict[str, Any]) -> ActionResult:  # type: ignore[no-untyped-def]
        current_context().require("exceptions.manage", company_id=context.company_id)
        return ActionResult(True, "Should not get here when automatic")


class GreedyCheck(FakeCheck):
    code = "test.greedy"


PROVIDERS = (FakeDraft, FakeNudge, FakeMoney, FakeGreedy)


def cand(fp: str, severity: str = "medium", branch: UUID | None = None, amount: str | None = "100",
         summary: str | None = None) -> Any:
    def make(company_id: UUID) -> Candidate:
        return Candidate(fingerprint=fp, severity=severity, summary=summary or f"Problem {fp}",
                         recommended_action="Look into it", company_id=company_id, branch_id=branch,
                         amount=__import__("decimal").Decimal(amount) if amount else None,
                         records=(Record("test.thing", uuid4(), f"Thing {fp}"),), figures={"count": "3"})
    return make


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    import ziira.modules.intel.hooks  # noqa: F401 - defines the extension points

    points = extensions._points
    for impl in (FakeCheck, GreedyCheck):
        extensions._add_implementation(points[INTEL_CHECK], "intel", impl)
    for impl in PROVIDERS:
        extensions._add_implementation(points[INTEL_ACTION], "intel", impl)
    s = make_stock_shop(client, registry, "Act Co")
    registry.enable(s["tenant_id"], "intel")
    s["accountant"] = s["user"]("acct", "Accountant", None)
    s["finance"] = s["user"]("fin", "Finance Manager", None)
    yield s
    for impl in (FakeCheck, GreedyCheck):
        points[INTEL_CHECK].implementations.remove(("intel", impl))
    for impl in PROVIDERS:
        points[INTEL_ACTION].implementations.remove(("intel", impl))


@pytest.fixture(autouse=True)
def reset() -> None:
    PLAN["candidates"] = []
    SEEN.clear()


def set_level(client, shop, level: int, headers: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    return client.patch(f"/api/v1/companies/{shop['company_id']}/settings", headers=headers or shop["owner"],
                        json={"intel_action_level": level})


def run(shop, only=("test.act",)):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return engine.run_company(s, shop["company_id"], today=date(2026, 10, 14), only=set(only))


def finding_id(client, shop, fp: str) -> str:  # type: ignore[no-untyped-def]
    items = client.get(f"{INTEL}/findings", headers=shop["owner"], params={"search": f"Problem {fp}"}).json()
    return next(f["id"] for f in items if f["summary"] == f"Problem {fp}")


def proposals(client, shop, fid: str, who: str = "owner") -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    r = client.get(f"{INTEL}/findings/{fid}/actions", headers=shop[who])
    assert r.status_code == 200, r.text
    return r.json()


def of_type(items: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(p for p in items if p["action_type"] == kind)


def approve(client, shop, pid: str, who: str = "owner", **body):  # type: ignore[no-untyped-def]
    return client.post(f"{INTEL}/actions/{pid}/approve", headers=shop[who], json=body)


def audit_actions(shop, action: str) -> list[Any]:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return list(s.execute(text("select channel, user_id, changes from kernel.audit_log where action = :a "
                                   "order by id"), {"a": action}).all())


# --------------------------------------------------------------------------- level gating
def test_no_suggestions_at_level_1_or_2_and_they_appear_at_3(client, shop) -> None:  # type: ignore[no-untyped-def]
    PLAN["candidates"] = [cand("g1")]
    run(shop)
    fid = finding_id(client, shop, "g1")
    assert proposals(client, shop, fid) == []
    assert set_level(client, shop, 2).status_code == 200
    run(shop)
    assert proposals(client, shop, fid) == []
    assert set_level(client, shop, 3).status_code == 200
    run(shop)
    found = proposals(client, shop, fid)
    assert {p["action_type"] for p in found} == {"test.draft", "test.nudge"}
    draft = of_type(found, "test.draft")
    assert draft["status"] == "proposed" and draft["level_at_proposal"] == 3 and draft["params"] == {
        "quantity": "5", "code": "ABC"}
    assert draft["description"] == "Draft for: Problem g1" and draft["facts"] == {"Why": "a test"}
    assert draft["can_decide"] is True and draft["needs_permission"] == "exceptions.manage"
    assert SEEN == []                                          # level 3 never acts by itself, whatever the rules
    events = [e["event"] for e in client.get(f"{INTEL}/findings/{fid}", headers=shop["owner"]).json()["events"]]
    assert events.count("action_proposed") == 2


def test_suggestions_are_not_repeated_and_a_rejected_one_stays_rejected(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    PLAN["candidates"] = [cand("d1")]
    run(shop)
    run(shop)
    run(shop)
    fid = finding_id(client, shop, "d1")
    found = proposals(client, shop, fid)
    assert len(found) == 2
    draft = of_type(found, "test.draft")
    assert client.post(f"{INTEL}/actions/{draft['id']}/reject", headers=shop["owner"], json={"reason": " "}
                       ).status_code == 422
    done = client.post(f"{INTEL}/actions/{draft['id']}/reject", headers=shop["owner"], json={"reason": "Not needed"})
    assert done.status_code == 200 and done.json()["status"] == "rejected" and done.json()["decision_note"] == "Not needed"
    run(shop)
    assert [p["status"] for p in proposals(client, shop, fid) if p["action_type"] == "test.draft"] == ["rejected"]
    assert client.post(f"{INTEL}/actions/{draft['id']}/reject", headers=shop["owner"], json={"reason": "again"}
                       ).status_code == 409
    assert approve(client, shop, draft["id"]).status_code == 409                # a rejected one cannot be approved
    assert audit_actions(shop, "intel.action.rejected")


def test_suggestions_expire_when_the_finding_closes(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    PLAN["candidates"] = [cand("x1"), cand("x2")]
    run(shop)
    f1, f2 = finding_id(client, shop, "x1"), finding_id(client, shop, "x2")
    PLAN["candidates"] = [cand("x2")]
    run(shop)                                                   # x1 cleared by itself (a state check)
    assert {p["status"] for p in proposals(client, shop, f1)} == {"expired"}
    assert {p["status"] for p in proposals(client, shop, f2)} == {"proposed"}
    pid = proposals(client, shop, f2)[0]["id"]
    assert client.post(f"{INTEL}/findings/{f2}/dismiss", headers=shop["owner"], json={"reason": "fine"}).status_code == 200
    assert {p["status"] for p in proposals(client, shop, f2)} == {"expired"}
    r = approve(client, shop, pid)
    assert r.status_code == 409 and not SEEN
    events = [e["event"] for e in client.get(f"{INTEL}/findings/{f1}", headers=shop["owner"]).json()["events"]]
    assert "action_expired" in events


def test_a_finding_that_comes_back_is_looked_at_again(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    PLAN["candidates"] = [cand("r1", summary="Problem r1 nodraft")]
    run(shop)
    fid = next(f["id"] for f in client.get(f"{INTEL}/findings", headers=shop["owner"],
                                           params={"search": "Problem r1"}).json())
    assert [p["action_type"] for p in proposals(client, shop, fid)] == ["test.nudge"]      # no draft for this one


def test_lowering_the_level_withdraws_what_was_waiting(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    PLAN["candidates"] = [cand("l1")]
    run(shop)
    fid = finding_id(client, shop, "l1")
    pid = of_type(proposals(client, shop, fid), "test.draft")["id"]
    set_level(client, shop, 1)
    r = approve(client, shop, pid)
    assert r.status_code == 422 and "level" in r.text.lower() and not SEEN          # off: not even by hand
    run(shop)
    assert {p["status"] for p in proposals(client, shop, fid)} == {"cancelled"}
    set_level(client, shop, 3)


# --------------------------------------------------------------------------- approving
def test_approving_does_it_as_the_approver_and_records_everything(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    PLAN["candidates"] = [cand("a1", branch=shop["branch_id"])]
    run(shop)
    fid = finding_id(client, shop, "a1")
    draft = of_type(proposals(client, shop, fid), "test.draft")
    r = approve(client, shop, draft["id"], who="manager", note="Looks right")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "executed" and body["result"]["ok"] and body["result"]["message"] == "Draft made (5)"
    assert body["result"]["created"][0]["label"] == "Draft 1" and body["decided_by_name"] == "manager"
    assert body["decision_note"] == "Looks right" and body["executed_at"]
    assert SEEN[-1]["automatic"] is False and SEEN[-1]["channel"] != "intelligence" and SEEN[-1]["user"]
    with system(shop) as s:
        assert s.execute(text("select count(*) from kernel.exception_item where dedupe_key = :k"),
                         {"k": f"draft:{draft['id']}"}).scalar_one() == 1
        log = s.execute(text("select mode, outcome, level, rule_id, actor_user_id from intel.action_log "
                             "where proposal_id = :p"), {"p": draft["id"]}).all()
    assert [(x.mode, x.outcome, x.level, x.rule_id) for x in log] == [("manual", "executed", 3, None)]
    assert log[0].actor_user_id is not None
    events = client.get(f"{INTEL}/findings/{fid}", headers=shop["owner"]).json()["events"]
    taken = next(e for e in events if e["event"] == "action_taken")
    assert taken["user_name"] == "manager" and "Draft made" in taken["note"]
    audited = audit_actions(shop, "intel.action.executed")
    assert audited and audited[-1].changes["type"] == "test.draft" and audited[-1].changes["mode"] == "manual"


def test_approving_twice_does_nothing_the_second_time(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    PLAN["candidates"] = [cand("i1")]
    run(shop)
    pid = of_type(proposals(client, shop, finding_id(client, shop, "i1")), "test.draft")["id"]
    assert approve(client, shop, pid).status_code == 200
    again = approve(client, shop, pid)
    assert again.status_code == 200 and again.json()["status"] == "executed"
    assert len([x for x in SEEN if x["type"] == "test.draft"]) == 1
    with system(shop) as s:
        assert s.execute(text("select count(*) from intel.action_log where proposal_id = :p"),
                         {"p": pid}).scalar_one() == 1


def test_approval_needs_the_actions_permission_where_the_finding_is(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    PLAN["candidates"] = [cand("p-hq", branch=shop["branch_id"]), cand("p-juja", branch=shop["juja"])]
    run(shop)
    hq, juja = finding_id(client, shop, "p-hq"), finding_id(client, shop, "p-juja")
    juja_draft = of_type(proposals(client, shop, juja), "test.draft")["id"]
    hq_draft = of_type(proposals(client, shop, hq), "test.draft")["id"]
    # a branch manager of HQ cannot see, so cannot approve, another branch's
    assert approve(client, shop, juja_draft, who="manager").status_code == 404
    assert client.get(f"{INTEL}/actions/{juja_draft}", headers=shop["manager"]).status_code == 404
    # an accountant sees findings but holds no right to the action
    assert client.get(f"{INTEL}/actions/{hq_draft}", headers=shop["accountant"]).json()["can_decide"] is False
    assert approve(client, shop, hq_draft, who="accountant").status_code == 403
    assert client.post(f"{INTEL}/actions/{hq_draft}/reject", headers=shop["accountant"],
                       json={"reason": "no"}).status_code == 403
    # the cashier cannot even open the screen
    assert approve(client, shop, hq_draft, who="cashier").status_code == 403
    assert not SEEN
    # the people who may, may
    assert approve(client, shop, juja_draft, who="boss").status_code == 200
    # "mine" lists what is waiting for me to decide
    mine = client.get(f"{INTEL}/actions", headers=shop["manager"], params={"mine": "true"}).json()
    assert hq_draft in {p["id"] for p in mine} and juja_draft not in {p["id"] for p in mine}
    assert all(p["status"] == "proposed" and p["can_decide"] for p in mine)
    nobody = client.get(f"{INTEL}/actions", headers=shop["accountant"], params={"mine": "true"}).json()
    assert nobody == []


def test_edited_parameters_are_checked_again(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    PLAN["candidates"] = [cand("e1")]
    run(shop)
    pid = of_type(proposals(client, shop, finding_id(client, shop, "e1")), "test.draft")["id"]
    for bad in ({"quantity": "0"}, {"quantity": "101"}, {"quantity": "abc"}, {"note": "x" * 21}, {"nope": "1"},
                {"code": "CHANGED"}):
        r = approve(client, shop, pid, params=bad)
        assert r.status_code == 422, (bad, r.text)
    assert not SEEN
    r = approve(client, shop, pid, params={"quantity": "7", "note": "ok", "code": "ABC"})
    assert r.status_code == 200 and r.json()["params"] == {"quantity": "7", "note": "ok", "code": "ABC"}
    assert SEEN[-1]["params"]["quantity"] == "7" and r.json()["result"]["message"] == "Draft made (7)"


def test_a_failed_action_is_recorded_changes_nothing_and_may_be_tried_again(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    PLAN["candidates"] = [cand("f1"), cand("f2")]
    run(shop)
    pid = of_type(proposals(client, shop, finding_id(client, shop, "f1")), "test.draft")["id"]
    r = approve(client, shop, pid, params={"quantity": "3", "note": "boom"})
    assert r.status_code == 200 and r.json()["status"] == "failed"
    assert r.json()["result"] == {"ok": False, "message": "The supplier is on hold", "created": []}
    with system(shop) as s:
        assert s.execute(text("select count(*) from kernel.exception_item where dedupe_key = :k"),
                         {"k": f"draft:{pid}"}).scalar_one() == 0
        assert s.execute(text("select outcome from intel.action_log where proposal_id = :p"),
                         {"p": pid}).scalar_one() == "failed"
    assert audit_actions(shop, "intel.action.failed")
    run(shop)
    assert [p["status"] for p in proposals(client, shop, finding_id(client, shop, "f1"))
            if p["action_type"] == "test.draft"] == ["failed"]                  # not proposed again
    ok = approve(client, shop, pid, params={"quantity": "3", "note": "fine"})   # a person may try again
    assert ok.json()["status"] == "executed"
    pid2 = of_type(proposals(client, shop, finding_id(client, shop, "f2")), "test.draft")["id"]
    crash = approve(client, shop, pid2, params={"quantity": "3", "note": "crash"})
    assert crash.json()["status"] == "failed" and "secret" not in crash.text         # internals are not shown


# --------------------------------------------------------------------------- level 4: rules and automatic actions
def test_a_rule_can_only_be_made_for_routine_actions(client, shop) -> None:  # type: ignore[no-untyped-def]
    body = {"company_id": str(shop["company_id"]), "daily_cap": 5}
    types = {t["type"]: t for t in client.get(f"{INTEL}/actions/types", headers=shop["owner"]).json()}
    assert types["test.nudge"]["can_run_by_rule"] is True
    assert types["test.draft"]["can_run_by_rule"] is False and types["test.draft"]["why_not_by_rule"]
    assert types["test.money"]["can_run_by_rule"] is False and "money" in types["test.money"]["why_not_by_rule"]
    assert "branch_id" in types["test.nudge"]["rule_schema"]["properties"]
    for kind in ("test.draft", "test.money", "test.unknown"):
        r = client.post(f"{INTEL}/automation/rules", headers=shop["owner"], json={**body, "action_type": kind})
        assert r.status_code == 422, (kind, r.text)
    for bad in ({"severity": "urgent"}, {"nope": 1}, {"max_amount": "-1"}, {"branch_id": str(uuid4())}):
        r = client.post(f"{INTEL}/automation/rules", headers=shop["owner"],
                        json={**body, "action_type": "test.nudge", "conditions": bad})
        assert r.status_code == 422, (bad, r.text)
    assert client.post(f"{INTEL}/automation/rules", headers=shop["manager"],
                       json={**body, "action_type": "test.nudge"}).status_code == 403
    assert not SEEN


def test_at_level_4_a_rule_lets_a_routine_action_run_by_itself(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 4)
    body = {"company_id": str(shop["company_id"]), "action_type": "test.nudge", "daily_cap": 10,
            "conditions": {"severity": "high"}, "note": "Chase high ones"}
    assert client.post(f"{INTEL}/automation/rules", headers=shop["finance"], json=body).status_code == 403   # not the owner
    rule = client.post(f"{INTEL}/automation/rules", headers=shop["owner"], json=body)
    assert rule.status_code == 201, rule.text
    rid = rule.json()["id"]
    assert rule.json()["conditions"] == {"severity": "high"} and rule.json()["paused"] is False
    PLAN["candidates"] = [cand("auto-hi", severity="high"), cand("auto-lo", severity="low")]
    result = run(shop)
    assert result.acted == 1
    hi, lo = finding_id(client, shop, "auto-hi"), finding_id(client, shop, "auto-lo")
    done = of_type(proposals(client, shop, hi), "test.nudge")
    assert done["status"] == "executed" and done["decided_by"] is None and "rule" in done["decision_note"]
    assert done["result"]["message"] == "Nudged"
    assert of_type(proposals(client, shop, lo), "test.nudge")["status"] == "proposed"      # no rule covers it
    assert of_type(proposals(client, shop, hi), "test.draft")["status"] == "proposed"      # never automatic
    assert [x for x in SEEN if x["type"] == "test.draft"] == []
    nudge = next(x for x in SEEN if x["type"] == "test.nudge")
    assert nudge["automatic"] is True and nudge["channel"] == "intelligence" and nudge["user"] is None
    assert nudge["can_nudge"] is True and nudge["can_post"] is False                          # exactly one permission
    log = client.get(f"{INTEL}/actions/log", headers=shop["owner"], params={"mode": "automatic"}).json()
    entry = next(e for e in log if e["finding_id"] == hi)
    assert entry["rule_id"] == rid and entry["outcome"] == "executed" and entry["level"] == 4
    assert entry["actor_user_id"] is None and entry["action_title"] == "Send a nudge"
    events = client.get(f"{INTEL}/findings/{hi}", headers=shop["owner"]).json()["events"]
    taken = next(e for e in events if e["event"] == "action_taken")
    assert taken["channel"] == "intelligence" and taken["user_name"] is None
    audited = audit_actions(shop, "intel.action.executed")
    assert audited[-1].channel == "intelligence" and audited[-1].user_id is None
    assert audited[-1].changes["rule"] == rid
    again = run(shop)
    assert again.acted == 0                                                                    # once only
    shown = client.get(f"{INTEL}/automation/rules", headers=shop["owner"]).json()
    assert next(r for r in shown if r["id"] == rid)["times_used"] == 1


def test_only_the_owner_makes_or_widens_a_rule_but_others_may_pause_or_switch_off(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 4)
    rule = client.post(f"{INTEL}/automation/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "action_type": "test.nudge", "daily_cap": 3}).json()
    path = f"{INTEL}/automation/rules/{rule['id']}"
    fin = shop["finance"]
    assert client.get(f"{INTEL}/automation/rules", headers=fin).status_code == 200
    assert client.patch(path, headers=fin, json={"daily_cap": 50}).status_code == 403
    assert client.patch(path, headers=fin, json={"conditions": {"severity": "low"}}).status_code == 403
    assert client.patch(path, headers=fin, json={"note": "x"}).status_code == 403
    paused = client.patch(path, headers=fin, json={"paused": True})
    assert paused.status_code == 200 and paused.json()["paused"] is True
    assert client.patch(path, headers=fin, json={"paused": False}).status_code == 403          # resuming is enabling
    assert client.patch(path, headers=fin, json={"enabled": False}).status_code == 200
    assert client.patch(path, headers=fin, json={"enabled": True}).status_code == 403
    assert client.patch(path, headers=shop["owner"], json={"enabled": True, "paused": False}).status_code == 200
    client.patch(path, headers=shop["owner"], json={"enabled": False})


def test_rules_do_nothing_below_level_4_and_obey_pause_and_branch(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 3)
    rule = client.post(f"{INTEL}/automation/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "action_type": "test.nudge", "daily_cap": 10,
        "conditions": {"branch_id": str(shop["branch_id"])}}).json()
    PLAN["candidates"] = [cand("lv3", branch=shop["branch_id"])]
    assert run(shop).acted == 0
    pid = of_type(proposals(client, shop, finding_id(client, shop, "lv3")), "test.nudge")["id"]
    assert client.get(f"{INTEL}/actions/{pid}", headers=shop["owner"]).json()["status"] == "proposed"
    set_level(client, shop, 4)
    paused = client.patch(f"{INTEL}/automation/rules/{rule['id']}", headers=shop["owner"], json={"paused": True})
    assert paused.status_code == 200 and paused.json()["paused"] is True
    assert run(shop).acted == 0
    PLAN["candidates"] = [cand("lv3", branch=shop["branch_id"]), cand("elsewhere", branch=shop["juja"])]
    client.patch(f"{INTEL}/automation/rules/{rule['id']}", headers=shop["owner"], json={"paused": False})
    assert run(shop).acted == 1                                       # lv3 (HQ) only: the rule is for the HQ branch
    assert client.get(f"{INTEL}/actions/{pid}", headers=shop["owner"]).json()["status"] == "executed"
    far = of_type(proposals(client, shop, finding_id(client, shop, "elsewhere")), "test.nudge")
    assert far["status"] == "proposed"
    client.patch(f"{INTEL}/automation/rules/{rule['id']}", headers=shop["owner"], json={"enabled": False})


def test_the_daily_limit_and_the_amount_limit_hold(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 4)
    for r in client.get(f"{INTEL}/automation/rules", headers=shop["owner"]).json():
        client.patch(f"{INTEL}/automation/rules/{r['id']}", headers=shop["owner"], json={"enabled": False})
    rule = client.post(f"{INTEL}/automation/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "action_type": "test.nudge", "daily_cap": 2,
        "conditions": {"max_amount": "500"}}).json()
    PLAN["candidates"] = [cand(f"cap{i}", amount="100") for i in range(4)] + [cand("big", amount="900"),
                                                                           cand("noamount", amount=None)]
    result = run(shop)
    states = {fp: of_type(proposals(client, shop, finding_id(client, shop, fp)), "test.nudge")["status"]
              for fp in ("cap0", "cap1", "cap2", "cap3", "big", "noamount")}
    assert sum(1 for v in states.values() if v == "executed") == 2 and result.acted == 2      # the daily cap
    assert states["big"] == "proposed"                                                        # over the amount limit
    assert client.patch(f"{INTEL}/automation/rules/{rule['id']}", headers=shop["owner"],
                        json={"daily_cap": 0}).status_code == 422
    assert run(shop).acted == 0                                                               # nothing more today
    client.patch(f"{INTEL}/automation/rules/{rule['id']}", headers=shop["owner"], json={"enabled": False})


def test_an_automatic_action_cannot_do_more_than_its_one_permission(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 4)
    for r in client.get(f"{INTEL}/automation/rules", headers=shop["owner"]).json():
        client.patch(f"{INTEL}/automation/rules/{r['id']}", headers=shop["owner"], json={"enabled": False})
    client.post(f"{INTEL}/automation/rules", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "action_type": "test.greedy", "daily_cap": 5})
    PLAN["candidates"] = [cand("gr1")]
    with system(shop) as s:
        engine.run_company(s, shop["company_id"], today=date(2026, 10, 14), only={"test.greedy"})
    # the fake greedy check is the same fake as FakeCheck: its candidates come from the same plan
    fid = finding_id(client, shop, "gr1")
    greedy = of_type(proposals(client, shop, fid), "test.greedy")
    assert greedy["status"] == "failed" and "permission" in greedy["result"]["message"]
    assert greedy["decided_by"] is None
    with system(shop) as s:
        assert s.execute(text("select count(*) from kernel.exception_item where kind = 'automatic_action_failed'")
                         ).scalar_one() >= 1                      # a failure is shown to people, never retried
    with system(shop) as s:
        engine.run_company(s, shop["company_id"], today=date(2026, 10, 14), only={"test.greedy"})
    assert of_type(proposals(client, shop, fid), "test.greedy")["status"] == "failed"
    # the same action by a person who holds the permission is fine
    manual = approve(client, shop, greedy["id"])
    assert manual.json()["status"] == "executed"
    for r in client.get(f"{INTEL}/automation/rules", headers=shop["owner"]).json():
        client.patch(f"{INTEL}/automation/rules/{r['id']}", headers=shop["owner"], json={"enabled": False})


def test_the_engine_refuses_a_non_automatic_provider_whatever_a_rule_says(client, shop) -> None:  # type: ignore[no-untyped-def]
    """Even a rule written straight into the database cannot make a draft, a price or a money action automatic."""
    set_level(client, shop, 4)
    for r in client.get(f"{INTEL}/automation/rules", headers=shop["owner"]).json():
        client.patch(f"{INTEL}/automation/rules/{r['id']}", headers=shop["owner"], json={"enabled": False})
    with system(shop) as s:
        for kind in ("test.draft", "test.money"):
            s.execute(text("insert into intel.auto_rule (tenant_id, company_id, action_type, daily_cap) "
                           "values (kernel.current_tenant(), :c, :t, 50)"), {"c": str(shop["company_id"]), "t": kind})
    PLAN["candidates"] = [cand("hard1")]
    run(shop)
    fid = finding_id(client, shop, "hard1")
    assert of_type(proposals(client, shop, fid), "test.draft")["status"] == "proposed"
    assert not [x for x in SEEN if x["type"] in ("test.draft", "test.money")]
    with system(shop) as s:
        s.execute(text("delete from intel.auto_rule where action_type in ('test.draft', 'test.money')"))


# --------------------------------------------------------------------------- the level itself
def test_raising_the_level_to_3_or_4_needs_the_owner_and_is_audited(client, shop) -> None:  # type: ignore[no-untyped-def]
    set_level(client, shop, 1)
    role = client.post("/api/v1/roles", headers=shop["owner"],
                       json={"name": "Settings admin", "permissions": ["settings.manage"]}).json()
    u = client.post("/api/v1/users", headers=shop["owner"], json={
        "full_name": "Setter", "email": f"setter@{shop['code']}.test", "password": "setter-pass-1"}).json()
    client.post(f"/api/v1/users/{u['id']}/roles", headers=shop["owner"], json={"role_id": role["id"], "scope": "tenant"})
    from tests.conftest import sign_in

    setter = sign_in(client, shop["code"], f"setter@{shop['code']}.test", "setter-pass-1").headers
    assert set_level(client, shop, 2, setter).status_code == 200                 # asking people to explain: as before
    for level in (3, 4):
        denied = set_level(client, shop, level, setter)
        assert denied.status_code == 403 and "intel.automation" in denied.text
    assert set_level(client, shop, 3).status_code == 200                          # the owner may
    assert set_level(client, shop, 1, setter).status_code == 200                  # anyone with settings may lower it
    rows = audit_actions(shop, "update")
    changes = [c.changes for c in rows if c.changes and "intel_action_level" in c.changes]
    assert {"from": 1, "to": 3} in [c["intel_action_level"] for c in changes]


# --------------------------------------------------------------------------- safety nets
def test_a_provider_that_breaks_does_not_stop_the_others(client, shop) -> None:  # type: ignore[no-untyped-def]
    class Broken(ActionProvider):
        type = "test.broken"
        title = "Broken"
        check_codes = ("test.act",)
        needs_permission = "findings.manage"

        def proposes(self, session, finding):  # type: ignore[no-untyped-def]
            raise RuntimeError("bad provider")

        def execute(self, session, context, params):  # type: ignore[no-untyped-def]
            return ActionResult(True, "")

    point = extensions._points[INTEL_ACTION]
    extensions._add_implementation(point, "intel", Broken)
    try:
        set_level(client, shop, 3)
        PLAN["candidates"] = [cand("br1")]
        run(shop)
        fid = finding_id(client, shop, "br1")
        assert {p["action_type"] for p in proposals(client, shop, fid)} >= {"test.draft", "test.nudge"}
        with system(shop) as s:
            assert s.execute(text("select count(*) from kernel.exception_item where kind = 'action_provider_failed'")
                             ).scalar_one() >= 1
    finally:
        point.implementations.remove(("intel", Broken))


def test_the_rule_vocabulary_is_checked_without_a_database() -> None:
    schema = FakeDraft.params_schema
    assert action_rules.validate_values(schema, {"quantity": "2.50", "note": " hi "}) == {"quantity": "2.5", "note": "hi"}
    assert action_rules.validate_values(schema, {"quantity": 3}) == {"quantity": "3"}
    for bad in ({}, {"quantity": True}, {"quantity": "1e999"}, {"quantity": 0.5}, {"quantity": "1", "x": 1}):
        with pytest.raises(action_rules.ParamError):
            action_rules.validate_values(schema, bad)
    assert action_rules.params_hash({"a": 1, "b": 2}) == action_rules.params_hash({"b": 2, "a": 1})
    assert action_rules.auto_refusal(auto_allowed=True, needs_permission="findings.manage") is None
    assert action_rules.auto_refusal(auto_allowed=False, needs_permission="findings.manage")
    assert action_rules.auto_refusal(auto_allowed=True, needs_permission="prices.manage")


def test_every_registered_action_is_well_formed_and_the_automatic_ones_stay_clear_of_money(registry) -> None:  # type: ignore[no-untyped-def]
    """Review list: every real action provider, once all units are loaded. An automatic one must not need a money
    permission and its code must not reach the books, payments, stock, prices or credit limits."""
    import ziira.modules.crm.hooks  # noqa: F401
    import ziira.modules.finance.hooks  # noqa: F401
    import ziira.modules.inventory.hooks  # noqa: F401
    import ziira.modules.people.hooks  # noqa: F401
    import ziira.modules.pos.hooks  # noqa: F401
    import ziira.modules.purchasing.hooks  # noqa: F401

    found = [impl for _, impl in extensions._points[INTEL_ACTION].implementations if not impl.__module__.startswith("tests")]
    assert {impl.type for impl in found} >= {
        "intel.nudge_exceptions_reviewers", "purchasing.draft_purchase_request", "purchasing.propose_price_update",
        "pos.send_payment_reminder", "pos.hold_credit", "people.nudge_approver", "finance.ask_for_reconciliation"}
    assert len({impl.type for impl in found}) == len(found)
    for impl in found:
        assert action_rules.check_type_name(impl.type) and impl.type.startswith(impl.__module__.split(".")[2] + ".")
        assert impl.title and impl.check_codes and impl.needs_permission
        action_rules.validate_values(impl.params_schema, {}) if not impl.params_schema.get("required") else None
        if impl.auto_allowed:
            assert impl.needs_permission not in action_rules.MONEY_PERMISSIONS, impl.type
            source = inspect.getsource(impl)
            for forbidden in action_rules.FORBIDDEN_FOR_AUTO:
                assert forbidden not in source, f"{impl.type} is automatic but uses {forbidden}"
