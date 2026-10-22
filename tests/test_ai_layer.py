"""The AI layer end to end with a scripted provider (`FakeLlm`): consent, budget, what is sent, explanations and
rankings that must match the facts, and Ask Ziira answering from tools within the asker's access.

No real AI service is called anywhere here; see docs/ai.md for what is untested live.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import ADMIN_URL, TENANT_DB_PREFIX
from tests.pos_helpers import make_sales_shop, sell
from tests.stock_helpers import system
from ziira.kernel import extensions, jobs
from ziira.kernel.config import get_settings
from ziira.kernel.context import system_context
from ziira.modules.intel.domain.ai_rules import CONSENT_VERSION
from ziira.modules.intel.domain.llm import LlmError, LlmReply, LlmUsage
from ziira.modules.intel.fake_llm import FakeLlm
from ziira.modules.intel.public import INTEL_CHECK, Candidate, CheckContext, IntelCheck, Record, top_findings
from ziira.modules.intel.services import ai, engine, explain

INTEL = "/api/v1/intel"
PLAN: list[Any] = []


class AiCheck(IntelCheck):
    """Reports what the test planned (candidates built from the company id)."""

    code = "test.ai"
    title = "A check for the AI tests"
    area = "stock"
    description = "For tests"
    params: dict[str, Any] = {}

    def run(self, session, ctx: CheckContext) -> list[Candidate]:  # type: ignore[no-untyped-def]
        return [make(ctx) for make in PLAN]


def candidate(fp: str, summary: str, severity: str = "medium", amount: str | None = "100.00", branch: UUID | None = None,
              records: tuple[Record, ...] = (), figures: dict[str, str] | None = None) -> Any:
    def make(ctx: CheckContext) -> Candidate:
        return Candidate(fingerprint=fp, severity=severity, summary=summary, recommended_action="Look into it",
                         company_id=ctx.company_id, branch_id=branch, amount=Decimal(amount) if amount else None,
                         period_start=date(2026, 10, 1), records=records, figures=figures or {})
    return make


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    import ziira.modules.intel.hooks  # noqa: F401 - defines the extension points

    extensions._add_implementation(extensions._points[INTEL_CHECK], "intel", AiCheck)
    s = make_sales_shop(client, registry, "AI Co")
    for unit in ("intel", "command", "people"):
        registry.enable(s["tenant_id"], unit)
    s["jujamgr"] = s["user"]("jujamgr", "Branch Manager", s["juja"])
    s["fm2"] = s["user"]("fm2", "Finance Manager", None)
    s["acct"] = s["user"]("acct", "Accountant", None)
    sell(client, s)                                                    # one sale of 116.00 at Head office today
    yield s
    extensions._points[INTEL_CHECK].implementations.remove(("intel", AiCheck))


@pytest.fixture(autouse=True)
def fresh(monkeypatch, shop):  # type: ignore[no-untyped-def]
    """A clean scripted provider, the fake provider chosen, no usage or conversations left over, AI switched off."""
    FakeLlm.reset()
    monkeypatch.setattr(get_settings(), "ai_provider", "fake")
    monkeypatch.setattr(get_settings(), "ai_api_key", "")
    PLAN.clear()
    with system(shop) as s:
        for table in ("ai_usage", "ai_call_log", "ask_session", "ai_ranking"):
            s.execute(text(f"delete from intel.{table}"))
        s.execute(text("update kernel.company set settings = settings - 'ai_enabled' - 'ai_monthly_token_limit' "
                       "- 'ai_ask' - 'ai_explanations' - 'ai_auto_explain'"))
        s.execute(text("update intel.finding set explanation_ai = null, explanation_ai_at = null, "
                       "explanation_ai_tried_at = null"))


def settings_body(shop, **kw: Any) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return {"company_id": str(shop["company_id"]), **kw}


def enable(client, shop, **kw: Any) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    r = client.put(f"{INTEL}/ai/settings", headers=shop["owner"], json=settings_body(
        shop, enabled=True, accept_version=CONSENT_VERSION, language="en", **kw))
    assert r.status_code == 200, r.text
    return r.json()


def asking(client, who: str, shop, question: str = "How were sales?", **kw: Any):  # type: ignore[no-untyped-def]
    return client.post(f"{INTEL}/ask", headers=shop[who], json={"question": question, **kw})


def window() -> dict[str, str]:
    today = date.today()
    return {"date_from": (today - timedelta(days=3)).isoformat(), "date_to": (today + timedelta(days=1)).isoformat()}


def calls_log(client, shop) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    r = client.get(f"{INTEL}/ai/calls", headers=shop["owner"], params={"company_id": str(shop["company_id"])})
    assert r.status_code == 200, r.text
    return r.json()


def finding_id(shop, summary: str) -> UUID:  # type: ignore[no-untyped-def]
    from ziira.sdk import humanise_dates

    with system(shop) as s:
        return s.execute(text("select id from intel.finding where summary = :s order by first_seen_at desc limit 1"),
                         {"s": humanise_dates(summary)}).scalar_one()      # the engine writes dates in words


def detect(shop, *plans: Any) -> None:  # type: ignore[no-untyped-def]
    PLAN[:] = list(plans)
    with system(shop) as s:
        engine.run_company(s, shop["company_id"], today=date(2026, 10, 14), only={"test.ai"})


def no_transaction_open(shop) -> bool:  # type: ignore[no-untyped-def]
    """True when none of the tenant database's connections is sitting in an open transaction."""
    code = shop["code"]
    engine_ = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with engine_.connect() as c:
        n = c.execute(text("select count(*) from pg_stat_activity where datname = :d and pid <> pg_backend_pid() "
                           "and state like 'idle in transaction%'"), {"d": TENANT_DB_PREFIX + code}).scalar_one()
    engine_.dispose()
    return n == 0


# --------------------------------------------------------------------------- consent, switching on and off
def test_nothing_is_sent_before_an_owner_has_consented(client, shop) -> None:  # type: ignore[no-untyped-def]
    client.put(f"{INTEL}/ai/settings", headers=shop["owner"], json=settings_body(shop, enabled=False))  # withdraw any
    r = asking(client, "owner", shop)
    assert r.status_code == 409 and r.json()["reason"] == "not_enabled"
    with system(shop) as s:                                  # the setting alone, with no consent record, is not enough
        from ziira.kernel import company_settings

        company_settings.update_settings(s, shop["company_id"], {"ai_enabled": True})
    r = asking(client, "owner", shop)
    assert r.status_code == 409 and r.json()["reason"] == "no_consent"
    assert FakeLlm.calls == []
    assert {c["status"] for c in calls_log(client, shop)} == {"blocked:not_enabled", "blocked:no_consent"}


def test_switching_on_needs_the_current_text_accepted_and_is_recorded(client, shop) -> None:  # type: ignore[no-untyped-def]
    url = f"{INTEL}/ai/settings"
    shown = client.get(url, headers=shop["owner"], params={"company_id": str(shop["company_id"])}).json()
    assert shown["enabled"] is False and shown["consent_version"] == CONSENT_VERSION and shown["configured"] is True
    assert "Fake provider" in shown["consent_text"]["en"] and "Majina ya wateja" in shown["consent_text"]["sw"]
    refused = client.put(url, headers=shop["owner"], json=settings_body(shop, enabled=True))
    wrong = client.put(url, headers=shop["owner"], json=settings_body(shop, enabled=True, accept_version="old"))
    assert refused.status_code == wrong.status_code == 422
    done = enable(client, shop, monthly_token_limit=500_000)
    assert done["enabled"] is True and done["consent_valid"] is True and done["monthly_token_limit"] == 500_000
    record = done["consents"][0]
    assert record["action"] == "granted" and record["user_name"] == "AI Co Owner" and record["language"] == "en"
    assert record["text_version"] == CONSENT_VERSION and record["provider"] == "fake"
    with system(shop) as s:
        stored = s.execute(text("select consent_text, text_hash from intel.ai_consent where action = 'granted' "
                                "order by created_at desc limit 1")).one()
    assert "Customer A" in stored.consent_text and len(stored.text_hash) == 64


def test_only_an_owner_may_switch_it_on_and_the_log_is_theirs_to_read(client, shop) -> None:  # type: ignore[no-untyped-def]
    for who in ("manager", "fm2", "acct"):
        assert client.put(f"{INTEL}/ai/settings", headers=shop[who], json=settings_body(
            shop, enabled=True, accept_version=CONSENT_VERSION)).status_code == 403
        assert client.get(f"{INTEL}/ai/settings", headers=shop[who],
                          params={"company_id": str(shop["company_id"])}).status_code == 403
        assert client.get(f"{INTEL}/ai/calls", headers=shop[who],
                          params={"company_id": str(shop["company_id"])}).status_code == 403
    assert client.get(f"{INTEL}/ai/status", headers=shop["cashier"],
                      params={"company_id": str(shop["company_id"])}).status_code == 403


def test_switching_off_stops_every_call_at_once_and_is_recorded(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    assert asking(client, "manager", shop).status_code == 200
    off = client.put(f"{INTEL}/ai/settings", headers=shop["owner"], json=settings_body(shop, enabled=False))
    assert off.status_code == 200 and off.json()["enabled"] is False
    assert off.json()["consents"][0]["action"] == "revoked"
    before = len(FakeLlm.calls)
    assert asking(client, "manager", shop).status_code == 409
    assert len(FakeLlm.calls) == before
    status = client.get(f"{INTEL}/ai/status", headers=shop["manager"], params={"company_id": str(shop["company_id"])})
    assert status.json()["ask_available"] is False and status.json()["reason"] == "not_enabled"


def test_a_change_of_provider_needs_a_new_consent(client, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    assert asking(client, "manager", shop).status_code == 200
    monkeypatch.setattr(get_settings(), "ai_provider", "anthropic")           # the platform moves to another provider
    monkeypatch.setattr(get_settings(), "ai_api_key", "sk-test-0123456789abcdef")
    moved = asking(client, "manager", shop)
    assert moved.status_code == 409 and moved.json()["reason"] == "no_consent"
    shown = client.get(f"{INTEL}/ai/settings", headers=shop["owner"], params={"company_id": str(shop["company_id"])}).json()
    assert shown["consent_valid"] is False and shown["enabled"] is False and shown["provider"] == "anthropic"
    assert len(FakeLlm.calls) == 1


def test_a_consent_record_cannot_be_changed_or_removed(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    for statement in ("update intel.ai_consent set provider = provider", "delete from intel.ai_consent"):
        with pytest.raises(Exception, match="immutable"), system(shop) as s:
            s.execute(text(statement))


def test_each_use_can_be_switched_off_separately(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop, ask=False)
    r = asking(client, "manager", shop)
    assert r.status_code == 409 and r.json()["reason"] == "purpose_off"
    enable(client, shop, ask=True, explanations=False)
    assert asking(client, "manager", shop).status_code == 200
    detect(shop, candidate("p1", "Cement stock is 3 units against 10."))
    fid = finding_id(shop, "Cement stock is 3 units against 10.")
    r = client.post(f"{INTEL}/findings/{fid}/ai-explanation", headers=shop["owner"], json={})
    assert r.status_code == 409 and r.json()["reason"] == "purpose_off"


# --------------------------------------------------------------------------- budget
def test_the_monthly_token_limit_is_a_hard_stop(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop, monthly_token_limit=120)                       # one fake call uses 100 + 20 tokens
    assert asking(client, "manager", shop).status_code == 200
    blocked = asking(client, "manager", shop)
    assert blocked.status_code == 409 and blocked.json()["reason"] == "budget"
    assert len(FakeLlm.calls) == 1
    shown = client.get(f"{INTEL}/ai/settings", headers=shop["owner"], params={"company_id": str(shop["company_id"])}).json()
    assert shown["tokens_used"] == 120 and shown["calls"] == 1 and shown["unavailable_reason"] == "budget"
    assert shown["usage"][0]["input_tokens"] == 100 and shown["usage"][0]["output_tokens"] == 20
    assert [c["status"] for c in calls_log(client, shop)][:2] == ["blocked:budget", "ok"]
    enable(client, shop, monthly_token_limit=10_000)
    assert asking(client, "manager", shop).status_code == 200


def test_a_limit_of_zero_allows_nothing_and_a_call_is_asked_for_no_more_than_what_is_left(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop, monthly_token_limit=0)
    assert asking(client, "manager", shop).json()["reason"] == "budget"
    enable(client, shop, monthly_token_limit=700)
    asking(client, "manager", shop)
    assert FakeLlm.calls[0]["max_tokens"] <= 700


# --------------------------------------------------------------------------- what is sent
def test_personal_details_in_a_question_are_replaced_before_they_leave(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    asking(client, "manager", shop, "Does mary@example.com on +254 712 345 678 (tax id A123456789B) owe anything?")
    sent = FakeLlm.calls[0]["messages"][0].text
    for private in ("mary@example.com", "712 345 678", "A123456789B"):
        assert private not in sent
    assert "[email]" in sent and "[phone]" in sent and "[id]" in sent
    log = calls_log(client, shop)[0]
    assert len(log["prompt_hash"]) == 64
    with system(shop) as s:                                  # the log keeps a hash, never the words
        dump = " ".join(str(v) for row in s.execute(text("select * from intel.ai_call_log")).all() for v in row)
    assert "mary@example.com" not in dump and "owe anything" not in dump


def test_the_call_log_says_who_asked_why_with_which_tools_and_how_much(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", window()), FakeLlm.say("Sales were 116.00 in total.")])
    assert asking(client, "manager", shop).status_code == 200
    ask_calls = [c for c in calls_log(client, shop) if c["purpose"] == "ask"]
    assert len(ask_calls) == 2 and {c["user_name"] for c in ask_calls} == {"manager"}
    assert all(c["status"] == "ok" and c["provider"] == "fake" and c["input_tokens"] == 100 and c["latency_ms"] is not None
               for c in ask_calls)
    assert any(t["name"] == "pos_sales_summary" for c in ask_calls for t in c["tool_calls"])


def test_a_failing_provider_is_logged_without_the_key_and_changes_nothing(client, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    secret = "sk-test-SECRETSECRETSECRET1234"
    monkeypatch.setattr(get_settings(), "ai_api_key", secret)
    enable(client, shop)
    FakeLlm.script.append(LlmError(f"401: invalid key {secret}", retryable=False, status=401))
    r = asking(client, "manager", shop)
    assert r.status_code == 502 and secret not in r.text
    failed = calls_log(client, shop)[0]
    assert failed["status"] == "error" and secret not in str(failed) and "[hidden]" in failed["detail"]
    sessions = client.get(f"{INTEL}/ask/sessions", headers=shop["manager"]).json()
    assert sessions == []                                            # nothing stored for an answer that never came


# --------------------------------------------------------------------------- explanations
LOW_STOCK = "Cement stock at Head office is 3 units, 7 below the reorder level of 10."


def low_stock(shop):  # type: ignore[no-untyped-def]
    return candidate("low", LOW_STOCK, severity="high", amount="350.00", branch=shop["branch_id"],
                     records=(Record("products.product", uuid4(), "Product CEM"),),
                     figures={"on_hand": "3", "reorder_level": "10"})


def test_an_explanation_is_kept_when_every_figure_comes_from_the_finding(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    detect(shop, low_stock(shop))
    fid = finding_id(shop, LOW_STOCK)
    FakeLlm.script.append(FakeLlm.say("Cement is running low: only 3 units are left against a reorder level of 10, "
                                      "and 350.00 is at stake."))
    r = client.post(f"{INTEL}/findings/{fid}/ai-explanation", headers=shop["owner"], json={})
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["explanation_ai"].startswith("Cement is running low") and detail["explanation_ai_at"]
    assert detail["explanation_ai_label"] == "AI-written"
    assert detail["summary"] == LOW_STOCK and detail["explanation"] is None            # the person's own field is separate
    assert "ai_explained" in [e["event"] for e in detail["events"]]
    prompt = FakeLlm.calls[0]["messages"][0].text
    assert LOW_STOCK in prompt and "350.00" in prompt and "on_hand: 3" in prompt.replace("Figure ", "")
    assert "Use ONLY numbers" in FakeLlm.calls[0]["system"] and FakeLlm.calls[0]["tools"] == []
    again = client.get(f"{INTEL}/findings/{fid}", headers=shop["owner"]).json()
    assert again["explanation_ai"] == detail["explanation_ai"]


def test_an_explanation_with_a_figure_that_is_not_in_the_finding_is_discarded(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    detect(shop, low_stock(shop))
    fid = finding_id(shop, LOW_STOCK)
    FakeLlm.script.append(FakeLlm.say("Cement is running low: only 3 units are left, about 42 days of sales."))
    r = client.post(f"{INTEL}/findings/{fid}/ai-explanation", headers=shop["owner"], json={})
    assert r.status_code == 422 and r.json()["error"] == "ai_rejected"
    kept = client.get(f"{INTEL}/findings/{fid}", headers=shop["owner"]).json()
    assert kept["explanation_ai"] is None and kept["summary"] == LOW_STOCK         # the deterministic text stays
    assert kept["explanation_ai_label"] is None
    last = calls_log(client, shop)[0]
    assert last["status"] == "rejected" and "42" in last["detail"] and last["input_tokens"] == 100


@pytest.mark.parametrize("reply", ["", "   "])
def test_an_empty_explanation_is_discarded(client, shop, reply: str) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    detect(shop, low_stock(shop))
    FakeLlm.script.append(FakeLlm.say(reply))
    r = client.post(f"{INTEL}/findings/{finding_id(shop, LOW_STOCK)}/ai-explanation", headers=shop["owner"], json={})
    assert r.status_code == 422


def test_names_of_people_reach_the_provider_as_labels_and_come_back_in_the_text(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    summary = "Mary Wanjiku voided 5 sales on 2026-10-12, worth 640.00."
    detect(shop, candidate("voids", summary, severity="high", amount="640.00",
                           records=(Record("people.employee", uuid4(), "Mary Wanjiku"),), figures={"voids": "5"}))
    fid = finding_id(shop, summary)
    FakeLlm.script.append(FakeLlm.say("Employee A voided 5 sales worth 640.00, which could be worth a conversation."))
    r = client.post(f"{INTEL}/findings/{fid}/ai-explanation", headers=shop["owner"], json={})
    assert r.status_code == 200, r.text
    prompt = FakeLlm.calls[0]["messages"][0].text
    assert "Mary Wanjiku" not in prompt and prompt.count("Employee A") >= 2
    assert r.json()["explanation_ai"].startswith("Mary Wanjiku voided 5 sales")


def test_only_those_who_manage_findings_may_ask_for_an_explanation(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    detect(shop, low_stock(shop))
    fid = finding_id(shop, LOW_STOCK)
    FakeLlm.script.append(FakeLlm.say("Only 3 units are left against a reorder level of 10."))
    assert client.post(f"{INTEL}/findings/{fid}/ai-explanation", headers=shop["manager"], json={}).status_code == 403
    assert client.post(f"{INTEL}/findings/{fid}/ai-explanation", headers=shop["cashier"], json={}).status_code == 403
    assert client.post(f"{INTEL}/findings/{fid}/ai-explanation", headers=shop["fm2"], json={"language": "sw"}).status_code == 200
    assert "Swahili" in FakeLlm.calls[0]["system"]
    assert client.post(f"{INTEL}/findings/{uuid4()}/ai-explanation", headers=shop["fm2"], json={}).status_code == 404


def test_the_background_job_explains_a_few_new_findings_with_no_transaction_open(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop, auto_explain=True)
    summaries = [f"Stock problem number {i} is 3 units against 10." for i in range(7)]
    detect(shop, *[candidate(f"auto{i}", s, severity="high", amount=f"{100 + i}.00") for i, s in enumerate(summaries)])
    seen: list[bool] = []

    def reply(_: dict[str, Any]) -> LlmReply:
        seen.append(no_transaction_open(shop))
        return FakeLlm.say("There are 3 units against 10.")

    FakeLlm.script.extend([reply] * 20)
    system_context(shop["tenant_id"])
    assert jobs.run_unbound(shop["tenant_id"], only="intel.ai_explain", force=True) == 1
    assert len(seen) == explain.EXPLANATIONS_PER_RUN == 5 and all(seen)                # rate limited, nothing held open
    with system(shop) as s:
        done = s.execute(text("select count(*) from intel.finding where explanation_ai is not null and "
                              "summary like 'Stock problem number%'")).scalar_one()
    assert done == 5
    jobs.run_unbound(shop["tenant_id"], only="intel.ai_explain", force=True)                 # the next two
    assert len(seen) == 7


def test_the_background_job_does_nothing_unless_switched_on(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop, auto_explain=False)
    detect(shop, candidate("quiet", "Quiet problem of 3 units.", severity="high"))
    system_context(shop["tenant_id"])
    jobs.run_unbound(shop["tenant_id"], only="intel.ai_explain", force=True)
    assert FakeLlm.calls == []


def test_a_failed_automatic_attempt_is_not_repeated_straight_away(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop, auto_explain=True)
    detect(shop, candidate("flaky", "Flaky problem of 3 units.", severity="high"))
    FakeLlm.script.append(LlmError("busy", retryable=True, status=529))
    system_context(shop["tenant_id"])
    jobs.run_unbound(shop["tenant_id"], only="intel.ai_explain", force=True)
    jobs.run_unbound(shop["tenant_id"], only="intel.ai_explain", force=True)
    assert len(FakeLlm.calls) == 1


# --------------------------------------------------------------------------- ranking
def ranking_plans(shop):  # type: ignore[no-untyped-def]
    return [candidate(f"r{i}", f"Ranked problem {i} of {sev}.", severity=sev, amount=amt)
            for i, (sev, amt) in enumerate((("critical", "5000.00"), ("high", "900.00"), ("high", "100.00"),
                                            ("medium", "50.00"), ("low", "10.00")), start=1)]


def top(shop) -> list[str]:  # type: ignore[no-untyped-def]
    system_context(shop["tenant_id"])
    with system(shop) as s:
        from ziira.sdk import current_context

        return [f.summary for f in top_findings(s, current_context(), 5) if f.summary.startswith("Ranked problem")]


def ranked_reasons(shop) -> dict[str, str | None]:  # type: ignore[no-untyped-def]
    system_context(shop["tenant_id"])
    with system(shop) as s:
        from ziira.sdk import current_context

        return {f.summary: f.reason for f in top_findings(s, current_context(), 8) if f.summary.startswith("Ranked")}


def order_reply(aliases: list[str], reason: str = "Most urgent") -> LlmReply:
    import json

    return FakeLlm.say(json.dumps({"order": [{"id": a, "reason": reason} for a in aliases]}))


def test_a_valid_ai_ordering_changes_the_order_and_carries_its_reasons(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    detect(shop, *ranking_plans(shop))
    base = top(shop)
    assert base[0].startswith("Ranked problem 1") and base[-1].startswith("Ranked problem 5")
    prompt_ids = {}
    FakeLlm.script.append(lambda call: (prompt_ids.update(prompt=call["messages"][0].text), order_reply(
        ["F5", "F4", "F3", "F2", "F1"], "Check this first"))[1])
    system_context(shop["tenant_id"])
    assert explain.rank_company(shop["tenant_id"], shop["company_id"]) is True
    assert "F1 | severity" in prompt_ids["prompt"] and "money at stake" in prompt_ids["prompt"]
    changed = top(shop)
    assert changed != base and sorted(changed) == sorted(base)
    assert set(ranked_reasons(shop).values()) == {"Check this first"}


def test_an_ordering_that_is_not_a_permutation_is_ignored(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    detect(shop, *ranking_plans(shop))
    base = top(shop)
    system_context(shop["tenant_id"])
    for bad in (["F1", "F2", "F3", "F4"], ["F1", "F1", "F2", "F3", "F4"], ["F1", "F2", "F3", "F4", "F9"]):
        FakeLlm.script.append(order_reply(bad))
        assert explain.rank_company(shop["tenant_id"], shop["company_id"]) is False
    FakeLlm.script.append(FakeLlm.say("I would start with the big one."))
    assert explain.rank_company(shop["tenant_id"], shop["company_id"]) is False
    assert top(shop) == base
    assert [c["status"] for c in calls_log(client, shop)[:4]] == ["rejected"] * 4


def test_a_reason_with_an_invented_figure_throws_the_ordering_away(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    detect(shop, *ranking_plans(shop))
    base = top(shop)
    FakeLlm.script.append(order_reply(["F5", "F4", "F3", "F2", "F1"], "Costs 777 a day"))
    system_context(shop["tenant_id"])
    assert explain.rank_company(shop["tenant_id"], shop["company_id"]) is False
    assert top(shop) == base


def test_an_old_ordering_is_not_used_and_a_new_finding_keeps_its_place(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    detect(shop, *ranking_plans(shop))
    FakeLlm.script.append(order_reply(["F5", "F4", "F3", "F2", "F1"]))
    system_context(shop["tenant_id"])
    explain.rank_company(shop["tenant_id"], shop["company_id"])
    detect(shop, *ranking_plans(shop), candidate("new", "Ranked problem 6 of critical.", severity="critical",
                                                 amount="9000.00"))
    assert top(shop)[0].startswith("Ranked problem 6")                  # the newest, most serious one is still first
    with system(shop) as s:
        s.execute(text("update intel.ai_ranking set computed_at = now() - interval '13 hours'"))
    assert top(shop)[:2] == ["Ranked problem 6 of critical.", "Ranked problem 1 of critical."]


def test_nothing_is_ranked_unless_the_assistant_is_on(client, shop) -> None:  # type: ignore[no-untyped-def]
    detect(shop, *ranking_plans(shop))
    system_context(shop["tenant_id"])
    assert explain.rank_company(shop["tenant_id"], shop["company_id"]) is False and FakeLlm.calls == []


# --------------------------------------------------------------------------- Ask Ziira
def test_ask_ziira_answers_from_a_tool_and_shows_its_sources(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", window()),
                           FakeLlm.say("Head office made 1 sale, worth 116.00 in total.")])
    r = asking(client, "manager", shop)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"] == "Head office made 1 sale, worth 116.00 in total." and body["ai_generated"] is True
    assert body["flagged"] is False and body["capped"] is None
    source = body["sources"][0]
    assert source["tool"] == "pos_sales_summary" and source["params"]["date_from"] == window()["date_from"]
    assert source["rows"][0]["branch"] == "Head office" and source["rows"][0]["sales_total"] == "116.00"
    assert source["summary"]["total_sales_count"] == 1
    first, second = FakeLlm.calls
    assert "pos_sales_summary" in first["tools"] and "inventory_low_stock" in first["tools"]
    assert "Today is" in first["system"] and str(shop["branch_id"]) in first["system"]
    results = second["messages"][-1].tool_results
    assert len(results) == 1 and '"sales_total":"116.00"' in results[0].content and not results[0].is_error
    again = client.get(f"{INTEL}/ask/sessions/{body['session_id']}", headers=shop["manager"]).json()
    assert [m["role"] for m in again["messages"]] == ["user", "assistant"]
    assert again["messages"][1]["sources"][0]["tool"] == "pos_sales_summary" and again["messages"][1]["ai_generated"]
    assert again["messages"][1]["tools_used"][0]["status"] == "ok"


def test_a_branch_manager_cannot_get_another_branchs_numbers(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    hq = str(shop["branch_id"])
    FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", {**window(), "branch_id": hq}),
                           FakeLlm.say("I could not read that branch.")])
    r = asking(client, "jujamgr", shop, "How did Head office do?")
    assert r.status_code == 200 and r.json()["sources"] == []
    refused = FakeLlm.calls[1]["messages"][-1].tool_results[0]
    assert refused.is_error and "116" not in refused.content and "access" in refused.content
    assert hq not in FakeLlm.calls[0]["system"]                          # the branch is not even in the list offered
    # without naming a branch, only the manager's own branch is counted: Juja sold nothing
    FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", window()), FakeLlm.say("There were no sales.")])
    r = asking(client, "jujamgr", shop)
    assert r.json()["sources"][0]["rows"] == [] and r.json()["sources"][0]["summary"]["total_sales"] == "0"
    # the same question from the Head office manager does show the sale
    FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", window()), FakeLlm.say("Sales were 116.00.")])
    assert asking(client, "manager", shop).json()["sources"][0]["summary"]["total_sales"] == "116.00"


def test_every_tool_filters_by_branch_for_a_branch_manager(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    other = str(shop["branch_id"])
    refused_everywhere = [
        ("pos_top_products", window()), ("pos_voids", window()), ("inventory_stock_on_hand", {"product": "CEM"}),
        ("inventory_low_stock", {}), ("finance_profit_and_loss", window()), ("finance_cash_position", window()),
        ("people_headcount", {}), ("command_figures", window())]
    for name, args in refused_everywhere:
        FakeLlm.reset()
        FakeLlm.script.extend([FakeLlm.tool(name, {**args, "branch_id": other}), FakeLlm.say("No.")])
        r = asking(client, "jujamgr", shop)
        assert r.status_code == 200, (name, r.text)
        assert r.json()["sources"] == [], name
        assert FakeLlm.calls[1]["messages"][-1].tool_results[0].is_error, name


def test_a_tool_the_person_may_not_use_is_not_offered_and_is_refused_if_called(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    FakeLlm.script.extend([FakeLlm.tool("people_leave_pending", {}), FakeLlm.say("I cannot see that.")])
    r = asking(client, "fm2", shop, "Who wants leave?")                  # a Finance Manager approves no leave
    assert r.status_code == 200
    assert "people_leave_pending" not in FakeLlm.calls[0]["tools"] and "people_headcount" in FakeLlm.calls[0]["tools"]
    refusal = FakeLlm.calls[1]["messages"][-1].tool_results[0]
    assert refusal.is_error and "not allowed" in refusal.content
    assert r.json()["sources"] == []
    used = client.get(f"{INTEL}/ask/sessions/{r.json()['session_id']}", headers=shop["fm2"]).json()["messages"][1]
    assert used["tools_used"][0] == {"tool": "people_leave_pending", "params": {}, "status": "refused"}


def test_a_tool_that_does_not_exist_or_has_bad_arguments_is_refused_not_run(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    FakeLlm.script.extend([FakeLlm.tool("run_sql", {"query": "select * from kernel.app_user"},
                                        ("pos_top_products", {"date_from": "tomorrow", "date_to": "2026-10-01"})),
                           FakeLlm.say("Sorry.")])
    assert asking(client, "manager", shop).status_code == 200
    first, second = FakeLlm.calls[1]["messages"][-1].tool_results
    assert first.is_error and "does not exist" in first.content
    assert second.is_error and "Invalid arguments" in second.content


def test_only_four_tools_run_at_a_time(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    many = [("inventory_low_stock", {})] * 6
    FakeLlm.script.extend([FakeLlm.tool(*many[0], *many[1:]), FakeLlm.say("Done.")])
    asking(client, "manager", shop)
    results = FakeLlm.calls[1]["messages"][-1].tool_results
    assert len(results) == 6 and sum(r.is_error for r in results) == 2


def test_the_tool_loop_stops_after_six_rounds_and_the_model_must_answer(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)

    def endless(call: dict[str, Any]) -> LlmReply:                    # a different limit each time: nothing is cached
        return FakeLlm.say("Here is what I found: 1 sale.") if not call["tools"] else FakeLlm.tool(
            "inventory_low_stock", {"limit": len(FakeLlm.calls)})

    FakeLlm.script.extend([endless] * 20)
    r = asking(client, "manager", shop)
    body = r.json()
    assert r.status_code == 200 and body["capped"] == "tool rounds" and body["answer"].startswith("Here is what")
    assert len(FakeLlm.calls) == 7 and FakeLlm.calls[-1]["tools"] == [] and len(FakeLlm.calls[0]["tools"]) > 5
    assert len(body["sources"]) == 6


def test_a_model_that_never_answers_gets_a_plain_fallback_and_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    FakeLlm.script.extend([lambda call: FakeLlm.tool("inventory_low_stock", {}) if call["tools"] else FakeLlm.say("")] * 10)
    body = asking(client, "manager", shop).json()
    assert "could not finish" in body["answer"] and body["flagged"] is True and body["flag_reason"] == "tool rounds"


def test_the_token_cap_ends_the_loop_early(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    big = LlmUsage(30_000, 12_000)
    FakeLlm.script.extend([
        lambda call: LlmReply(tool_calls=FakeLlm.tool("inventory_low_stock", {}).tool_calls, usage=big)
        if call["tools"] else FakeLlm.say("Short answer.", big)] * 5)
    body = asking(client, "manager", shop).json()
    assert body["capped"] == "tokens" and body["answer"] == "Short answer." and len(FakeLlm.calls) == 2


def test_a_figure_the_tools_never_returned_is_flagged_in_the_answer(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", window()),
                           FakeLlm.say("Sales were 999.00 across 1 sale.")])
    body = asking(client, "manager", shop).json()
    assert body["flagged"] is True and "999" in body["flag_reason"]
    assert body["answer"].endswith("Some figures could not be verified against your data.")
    stored = client.get(f"{INTEL}/ask/sessions/{body['session_id']}", headers=shop["manager"]).json()["messages"][1]
    assert stored["flagged"] is True
    FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", window()), FakeLlm.say("Mauzo yalikuwa 999.00.")])
    sw = asking(client, "manager", shop, language="sw").json()
    assert sw["answer"].endswith("Baadhi ya namba hazikuweza kuthibitishwa dhidi ya data yako.")
    assert "Swahili" in FakeLlm.calls[-2]["system"]


def test_figures_that_can_be_recomputed_from_the_tool_results_pass(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", window()),
                           FakeLlm.say("1 sale made 116.00; against the 84.00 target that is 32.00 over, "
                                       "and the target was 72% of sales.")])
    body = asking(client, "manager", shop, "Did we beat a target of 84 last week?").json()
    assert body["flagged"] is False, body


def alias_in(call: dict[str, Any]) -> str:
    """The label the provider was given for the employee in the tool result it is now reading."""
    import re

    found = re.search(r"Employee [A-Z]+", call["messages"][-1].tool_results[0].content)
    assert found, "the employee was not replaced by a label"
    return found.group()


def test_names_in_tool_results_are_labels_to_the_provider_and_real_names_in_the_answer(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    summary = "Mary Wanjiku voided 5 sales on 2026-10-13, worth 640.00."
    detect(shop, candidate("voids2", summary, severity="high", amount="640.00",
                           records=(Record("people.employee", uuid4(), "Mary Wanjiku"),), figures={"voids": "5"}))
    fid = str(finding_id(shop, summary))
    FakeLlm.script.extend([FakeLlm.tool("intel_finding_detail", {"finding_id": fid}),
                           lambda call: FakeLlm.say(f"{alias_in(call)} voided 5 sales worth 640.00.")])
    body = asking(client, "fm2", shop, "Tell me about the voids").json()
    sent_back = FakeLlm.calls[1]["messages"][-1].tool_results[0].content
    assert "Mary Wanjiku" not in sent_back and "Employee " in sent_back
    assert body["answer"] == "Mary Wanjiku voided 5 sales worth 640.00." and body["flagged"] is False
    assert "Mary Wanjiku" in str(body["sources"])                      # the person sees the real rows


def test_findings_through_ask_follow_the_askers_branches(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    detect(shop, candidate("hq-only", "Head office problem of 3 units.", branch=shop["branch_id"], severity="high"),
           candidate("juja-only", "Juja problem of 4 units.", branch=shop["juja"], severity="high"))
    FakeLlm.script.extend([FakeLlm.tool("intel_list_findings", {}), FakeLlm.say("There is 1 finding.")])
    body = asking(client, "jujamgr", shop, "What needs attention?").json()
    summaries = [r["summary"] for r in body["sources"][0]["rows"]]
    assert "Juja problem of 4 units." in summaries and "Head office problem of 3 units." not in summaries


def test_conversations_are_private_to_their_owner_and_open_to_an_owner_for_audit(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    sid = asking(client, "manager", shop, "How were sales?").json()["session_id"]
    other = asking(client, "jujamgr", shop, "And at Juja?").json()["session_id"]
    mine = client.get(f"{INTEL}/ask/sessions", headers=shop["manager"]).json()
    assert [s["id"] for s in mine] == [sid] and mine[0]["title"] == "How were sales?"
    assert client.get(f"{INTEL}/ask/sessions/{sid}", headers=shop["jujamgr"]).status_code == 404
    assert client.get(f"{INTEL}/ask/sessions/{sid}", headers=shop["fm2"]).status_code == 404
    assert client.get(f"{INTEL}/ask/sessions", headers=shop["jujamgr"], params={
        "everyone": True, "company_id": str(shop["company_id"])}).status_code == 403
    everyone = client.get(f"{INTEL}/ask/sessions", headers=shop["owner"], params={
        "everyone": True, "company_id": str(shop["company_id"])}).json()
    assert {s["id"] for s in everyone} == {sid, other}
    audit = client.get(f"{INTEL}/ask/sessions/{sid}", headers=shop["owner"])
    assert audit.status_code == 200 and audit.json()["user_name"] == "manager"
    # a conversation can be continued only by the person who started it
    assert asking(client, "jujamgr", shop, session_id=sid).status_code == 404
    assert asking(client, "manager", shop, "And last week?", session_id=sid).status_code == 200
    assert len(client.get(f"{INTEL}/ask/sessions/{sid}", headers=shop["manager"]).json()["messages"]) == 4


def test_only_those_with_the_ask_permission_can_ask(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    assert asking(client, "cashier", shop).status_code == 403
    for who in ("manager", "fm2", "acct", "owner"):
        assert asking(client, who, shop).status_code == 200, who


def test_a_question_is_needed_and_the_company_must_be_one_the_asker_can_use(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    assert asking(client, "manager", shop, "   ").status_code == 422
    assert asking(client, "manager", shop, company_id=str(uuid4())).status_code in (403, 404, 422)


def test_no_database_transaction_is_open_while_the_provider_is_called(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    seen: list[bool] = []

    def check(call: dict[str, Any]) -> LlmReply:
        seen.append(no_transaction_open(shop))
        return FakeLlm.tool("inventory_low_stock", {}) if len(seen) < 2 else FakeLlm.say("Nothing is low.")

    FakeLlm.script.extend([check, check])
    assert asking(client, "manager", shop).status_code == 200
    assert seen == [True, True]


def test_the_ai_status_tells_screens_what_to_show(client, shop) -> None:  # type: ignore[no-untyped-def]
    params = {"company_id": str(shop["company_id"])}
    off = client.get(f"{INTEL}/ai/status", headers=shop["manager"], params=params).json()
    assert off == {"company_id": str(shop["company_id"]), "ask_available": False, "explanations_available": False,
                   "reason": "not_enabled"}
    enable(client, shop)
    on = client.get(f"{INTEL}/ai/status", headers=shop["manager"], params=params).json()
    assert on["ask_available"] is True and on["explanations_available"] is True and on["reason"] is None


def test_old_history_is_forgotten(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    sid = asking(client, "manager", shop).json()["session_id"]
    with system(shop) as s:
        s.execute(text("update intel.ask_session set last_at = now() - interval '91 days' where id = :i"), {"i": sid})
        s.execute(text("update intel.ai_call_log set created_at = now() - interval '401 days'"))
    system_context(shop["tenant_id"])
    jobs.run_periodic(shop["tenant_id"], only="intel.purge_ai_history", force=True)
    assert client.get(f"{INTEL}/ask/sessions", headers=shop["manager"]).json() == []
    assert calls_log(client, shop) == []


def test_the_state_helper_reports_why_it_is_blocked(client, shop) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        state = ai.get_state(s, shop["company_id"])
    assert state.blocked("ask") == "not_enabled" and state.provider == "fake" and state.configured


def test_a_data_subject_request_finds_exports_and_erases_conversations(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.personal_data import parse_subject
    from ziira.modules.intel.privacy import IntelPersonalData

    enable(client, shop)
    summary = "Grace Achieng voided 4 sales on 2026-10-14, worth 480.00."
    detect(shop, candidate("voids3", summary, severity="high", amount="480.00",
                           records=(Record("people.employee", uuid4(), "Grace Achieng"),), figures={"voids": "4"}))
    fid = str(finding_id(shop, summary))
    FakeLlm.script.extend([FakeLlm.tool("intel_finding_detail", {"finding_id": fid}),
                           lambda call: FakeLlm.say(f"{alias_in(call)} voided 4 sales worth 480.00.")])
    sid = asking(client, "fm2", shop, "Tell me about the voids by Grace Achieng").json()["session_id"]
    provider = IntelPersonalData()
    subject = parse_subject("Grace Achieng", "254")
    with system(shop) as s:
        found = provider.find(s, shop["company_id"], subject)
        assert len(found) == 2 and {r.match for r in found} == {"possible"}
        exported = [provider.export(s, r)["ask_message"] for r in found]
        assert {e["role"] for e in exported} == {"user", "assistant"}
        assert any("Grace Achieng" in str(e) for e in exported)
        outcomes = [provider.anonymise(s, r, "requested") for r in found]
        assert {o.status for o in outcomes} == {"anonymised"}
        assert provider.find(s, shop["company_id"], subject) == []
        assert provider.retention(s, shop["company_id"])[0].code == "ask_conversations"
    mine = client.get(f"{INTEL}/ask/sessions/{sid}", headers=shop["fm2"]).json()
    assert mine["title"].startswith("[erased]") and "Grace" not in str(mine)
    assert all(m["content"] == "[removed]" and m["sources"] == [] for m in mine["messages"])
    assert mine["messages"][1]["tools_used"] == [{"tool": "intel_finding_detail", "status": "ok"}]


def test_the_command_center_shows_the_ai_reason_for_a_ranked_finding(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    detect(shop, *ranking_plans(shop))
    FakeLlm.script.append(order_reply(["F5", "F4", "F3", "F2", "F1"], "Check this first"))
    system_context(shop["tenant_id"])
    explain.rank_company(shop["tenant_id"], shop["company_id"])
    overview = client.get("/api/v1/command/overview", headers=shop["owner"], params={
        "company_id": str(shop["company_id"])}).json()
    ranked = [f for f in overview["top_findings"] if f["summary"].startswith("Ranked problem")]
    assert ranked and {f["reason"] for f in ranked} == {"Check this first"}
    others = [f for f in overview["top_findings"] if not f["summary"].startswith("Ranked problem")]
    assert all(f["reason"] is None for f in others)
