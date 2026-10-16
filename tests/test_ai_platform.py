"""AI providers managed in the Super Admin: keys (write-only), model choice per feature, test connection, the live model
list, gateway selection from the platform's tables (with the environment as fallback), the spend cap and usage,
consent ending when the default provider changes, the per-provider data-terms gate in production, permissions, the audit
trail without secrets, and the scored quality check. Providers are pretend HTTP servers: no real service is called."""

import json
import logging
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from tests.conftest import make_tenant
from tests.platform_helpers import API, staff
from tests.pos_helpers import make_sales_shop, sell
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session, tenant_session
from ziira.kernel.platform import ai as platform_ai
from ziira.modules.intel.domain.ai_rules import CONSENT_VERSION
from ziira.modules.intel.domain.llm import LlmReply, LlmUsage, ToolCall
from ziira.modules.intel.fake_llm import FakeLlm
from ziira.modules.intel.platform_ai import IntelAiPlatform
from ziira.modules.intel.services import ai, quality_check
from ziira.plugins.ai_gemini.provider import GeminiGenerateContent
from ziira.plugins.ai_openai.provider import OpenAIResponses

AI = f"{API}/operator/ai"
INTEL = "/api/v1/intel"
GKEY = "AIzaSyPlatformKey0123456789abcdef1234"
OKEY = "sk-proj-platformkey0123456789abcdefgh5678"
GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": "Sales were 116.00."}]}, "finishReason": "STOP"}],
             "usageMetadata": {"promptTokenCount": 1_000_000, "candidatesTokenCount": 100_000}}


class Net:
    """Pretend Gemini and OpenAI; answers by host and path, keeps what was asked."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.fail: dict[str, int] = {}

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        if host in self.fail:
            return httpx.Response(self.fail[host], json={"error": {"message": f"nope {request.headers}"}})
        if request.url.path.endswith("/models"):
            if "generativelanguage" in host:
                return httpx.Response(200, json={"models": [
                    {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-other", "supportedGenerationMethods": ["generateContent"]}]})
            return httpx.Response(200, json={"data": [{"id": "gpt-6-luna"}, {"id": "whisper-1"}, {"id": "gpt-x"}]})
        if "generativelanguage" in host:
            return httpx.Response(200, json=GEMINI_OK)
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
            "usage": {"input_tokens": 10, "output_tokens": 2}})


@pytest.fixture
def net(monkeypatch: pytest.MonkeyPatch) -> Net:
    pretend = Net()
    from ziira.modules.intel.public import HttpLlmProvider
    monkeypatch.setattr(HttpLlmProvider, "client_factory",
                        staticmethod(lambda timeout: httpx.Client(transport=httpx.MockTransport(pretend.handle))))
    monkeypatch.setattr(HttpLlmProvider, "sleep", staticmethod(lambda s: None))
    return pretend


@pytest.fixture(autouse=True)
def clean(client):  # type: ignore[no-untyped-def]
    def wipe() -> None:
        with master_session() as m:
            for table in ("ai_provider", "ai_usage", "ai_tenant_provider"):
                m.execute(text(f"delete from master.{table}"))
            m.execute(text("delete from master.platform_setting where key like 'ai.%'"))
        platform_ai.invalidate()

    wipe()
    yield
    wipe()


@pytest.fixture(scope="module")
def world(client, registry):  # type: ignore[no-untyped-def]
    import ziira.modules.intel.hooks  # noqa: F401

    shop = make_sales_shop(client, registry, "AI Platform Co")
    for unit in ("intel", "command", "people"):
        registry.enable(shop["tenant_id"], unit)
    sell(client, shop)
    return {"boss": staff(client, "superadmin")["headers"], "billing": staff(client, "billing")["headers"],
            "viewer": staff(client, "readonly")["headers"], "shop": shop}


def save(client, world, name: str, **body: Any) -> httpx.Response:  # type: ignore[no-untyped-def]
    return client.put(f"{AI}/providers/{name}", headers=world["boss"], json=body)


def provider_of(client, world, name: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    listed = client.get(AI, headers=world["boss"]).json()["providers"]
    return next(p for p in listed if p["name"] == name)


def make_default(client, world, name: str, key: str = GKEY) -> None:  # type: ignore[no-untyped-def]
    assert save(client, world, name, api_key=key, enabled=True).status_code == 200
    r = client.put(f"{AI}/default", headers=world["boss"], json={"provider": name, "confirm": name, "reason": "test"})
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- access and secrets
def test_only_the_superadmin_may_use_the_ai_page(client, world) -> None:  # type: ignore[no-untyped-def]
    for who in ("viewer", "billing"):
        assert client.get(AI, headers=world[who]).status_code == 403
        assert save(client, {**world, "boss": world[who]}, "gemini", enabled=False).status_code == 403
    assert client.get(AI, headers={}).status_code in (401, 403)
    listed = client.get(AI, headers=world["boss"]).json()
    assert {"anthropic", "gemini", "openai"} <= {p["name"] for p in listed["providers"]}
    assert listed["default_provider"] is None


def test_a_key_is_write_only_encrypted_and_never_in_the_trail_or_logs(client, world, caplog) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.DEBUG)
    r = save(client, world, "gemini", api_key=GKEY)
    assert r.status_code == 200 and r.json()["key_set"] and r.json()["key_last4"] == GKEY[-4:]
    assert GKEY not in r.text and GKEY not in client.get(AI, headers=world["boss"]).text
    with master_session() as m:
        stored = m.execute(text("select secret_encrypted from master.ai_provider where provider = 'gemini'")).scalar_one()
        trail = [x.detail for x in m.execute(text(
            "select detail from master.operator_action_log where action = 'ai_provider.save'"))]
    assert stored and GKEY not in stored and trail and GKEY not in json.dumps(trail, default=str)
    assert {"provider": "gemini", "fields": ["api_key"], "enabled": False} in trail
    assert GKEY not in caplog.text
    assert save(client, world, "gemini", api_key="short").status_code == 422
    assert save(client, world, "gemini", enabled=True, extra="x").status_code == 422
    assert save(client, world, "openai", enabled=True).status_code == 422            # no key yet
    assert save(client, world, "nothing", enabled=False).status_code == 404
    assert save(client, world, "gemini", clear_key=True).json()["key_set"] is False


# --------------------------------------------------------------------------- models and prices
def test_models_are_checked_against_the_live_list_and_priced_from_data_or_the_owner(client, world, net) -> None:  # type: ignore[no-untyped-def]
    save(client, world, "gemini", api_key=GKEY)
    p = provider_of(client, world, "gemini")
    assert p["models"] == {"explain": "gemini-2.5-flash", "rank": "gemini-2.5-flash", "ask": "gemini-3.8-flash"}
    best = next(m for m in p["model_choices"] if "best_value" in m["tiers"])
    assert best["id"] == "gemini-3.8-flash" and Decimal(best["input_per_mtok"]) == Decimal("0.75")
    refreshed = client.post(f"{AI}/providers/gemini/refresh-models", headers=world["boss"])
    assert refreshed.json() == {"count": 3, "missing_chosen": []}
    assert net.requests[-1].headers["x-goog-api-key"] == GKEY
    assert save(client, world, "gemini", models={"ask": "not-a-model"}).status_code == 422
    assert save(client, world, "gemini", models={"explain": "gemini-other"}).status_code == 200
    assert save(client, world, "gemini", models={"nonsense": "gemini-other"}).status_code == 422
    other = next(m for m in provider_of(client, world, "gemini")["model_choices"] if m["id"] == "gemini-other")
    assert other["in_catalog"] is False and other["input_per_mtok"] is None
    r = save(client, world, "gemini", price_overrides={"gemini-other": {"input": "0.2", "output": "0.9"}})
    assert next(m for m in r.json()["model_choices"] if m["id"] == "gemini-other")["output_per_mtok"] == "0.9"
    assert save(client, world, "gemini", price_overrides={"gemini-other": {"input": "-1", "output": "1"}}).status_code == 422
    # the OpenAI list is filtered to chat models by the plugin's prefixes
    save(client, world, "openai", api_key=OKEY)
    assert client.post(f"{AI}/providers/openai/refresh-models", headers=world["boss"]).json()["count"] == 2


def test_test_connection_reports_ok_latency_and_estimated_cost_or_the_failure_without_the_key(client, world, net) -> None:  # type: ignore[no-untyped-def]
    save(client, world, "gemini", api_key=GKEY)
    ok = client.post(f"{AI}/providers/gemini/test", headers=world["boss"]).json()
    assert ok["ok"] and ok["model"] == "gemini-3.8-flash" and ok["tokens_in"] == 1_000_000
    assert Decimal(ok["cost_usd"]) == Decimal("0.75") + Decimal("3.75") / 10        # 1M in, 100k out
    net.fail["generativelanguage.googleapis.com"] = 403
    bad = client.post(f"{AI}/providers/gemini/test", headers=world["boss"]).json()
    assert bad["ok"] is False and GKEY not in json.dumps(bad)
    assert provider_of(client, world, "gemini")["last_test_ok"] is False


# --------------------------------------------------------------------------- the gateway chooses from the tables
def test_the_gateway_uses_the_platform_provider_and_feature_models_else_the_environment(client, world, net, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "ai_provider", "fake")
    monkeypatch.setattr(get_settings(), "ai_api_key", "")
    env = platform_ai.runtime("ask")
    assert env is not None and env.provider == "fake" and env.source == "environment"
    make_default(client, world, "gemini")
    save(client, world, "gemini", models={"explain": "gemini-2.5-flash"})
    rt = platform_ai.runtime("ask")
    assert rt is not None and rt.source == "platform" and rt.provider == "gemini" and rt.model == "gemini-3.8-flash"
    explain = platform_ai.runtime("explain")
    assert explain is not None and explain.model == "gemini-2.5-flash"
    assert ai.provider("explain").model_id() == "gemini-2.5-flash"                    # type: ignore[union-attr]
    # a change from elsewhere is seen within the cache time, and at once in this process
    with master_session() as m:
        m.execute(text("update master.ai_provider set enabled = false where provider = 'gemini'"))
    assert platform_ai.runtime("ask") is not None
    platform_ai.invalidate()
    assert platform_ai.runtime("ask") is None
    # an operator-made exception moves one business to another provider
    save(client, world, "openai", api_key=OKEY, enabled=True)
    save(client, world, "gemini", enabled=True)
    code = world["shop"]["tenant_id"]
    with master_session() as m:
        tenant_code = m.execute(text("select code from master.tenant where id = :i"), {"i": str(code)}).scalar_one()
    done = client.put(f"{AI}/tenant-overrides/{tenant_code}", headers=world["boss"],
                      json={"provider": "openai", "reason": "pilot of the other provider"})
    assert done.status_code == 200 and done.json()[0]["provider"] == "openai"
    other = platform_ai.runtime("ask", code)
    assert other is not None and other.provider == "openai"
    assert client.put(f"{AI}/tenant-overrides/{tenant_code}", headers=world["boss"],
                      json={"provider": None, "reason": "back to normal"}).json() == []


def test_a_question_goes_to_the_chosen_provider_and_is_counted_with_its_cost(client, world, net) -> None:  # type: ignore[no-untyped-def]
    shop = world["shop"]
    make_default(client, world, "gemini")
    r = client.put(f"{INTEL}/ai/settings", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "enabled": True, "accept_version": CONSENT_VERSION, "language": "en"})
    assert r.status_code == 200 and r.json()["provider"] == "gemini" and r.json()["provider_label"] == "Google Gemini"
    asked = client.post(f"{INTEL}/ask", headers=shop["owner"], json={"question": "How were sales?"})
    assert asked.status_code == 200, asked.text
    sent = [q for q in net.requests if q.url.path.endswith(":generateContent")]
    assert sent and sent[0].headers["x-goog-api-key"] == GKEY
    usage = client.get(f"{AI}/usage", headers=world["boss"]).json()
    assert usage["providers"][0]["provider"] == "gemini" and Decimal(usage["providers"][0]["cost_usd"]) > 0
    assert usage["top_businesses"][0]["name"] == "AI Platform Co"
    assert GKEY not in json.dumps(usage)


# --------------------------------------------------------------------------- spend cap
def test_the_monthly_cap_refuses_calls_and_flags_the_owner(client, world, net) -> None:  # type: ignore[no-untyped-def]
    shop = world["shop"]
    make_default(client, world, "gemini")
    client.put(f"{INTEL}/ai/settings", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "enabled": True, "accept_version": CONSENT_VERSION, "language": "en",
        "monthly_token_limit": 50_000_000})
    assert client.put(f"{AI}/cap", headers=world["boss"], json={"cap_usd": "0.50"}).json()["monthly_cap_usd"] == "0.5"
    assert client.post(f"{INTEL}/ask", headers=shop["owner"], json={"question": "Sales?"}).status_code == 200   # costs 1.275
    blocked = client.post(f"{INTEL}/ask", headers=shop["owner"], json={"question": "Sales again?"})
    assert blocked.status_code == 409 and blocked.json()["reason"] == "spend_cap"
    usage = client.get(f"{AI}/usage", headers=world["boss"]).json()
    assert usage["cap_flag"] and client.get(AI, headers=world["boss"]).json()["cap_reached"] is True
    status = client.get(f"{INTEL}/ai/status", headers=shop["owner"], params={"company_id": str(shop["company_id"])})
    assert status.json()["reason"] == "spend_cap"
    client.put(f"{AI}/cap", headers=world["boss"], json={"cap_usd": None})
    assert client.post(f"{INTEL}/ask", headers=shop["owner"], json={"question": "Sales once more?"}).status_code == 200
    assert client.put(f"{AI}/cap", headers=world["boss"], json={"cap_usd": "abc"}).status_code == 422


# --------------------------------------------------------------------------- changing the default ends consents
def test_changing_the_default_needs_typing_it_a_reason_and_ends_every_consent(client, world, net) -> None:  # type: ignore[no-untyped-def]
    shop = world["shop"]
    make_default(client, world, "gemini")
    save(client, world, "openai", api_key=OKEY, enabled=True)
    client.put(f"{INTEL}/ai/settings", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "enabled": True, "accept_version": CONSENT_VERSION, "language": "en"})
    with tenant_session(shop["tenant_id"], admin=True) as s:
        assert IntelAiPlatform().valid_consents(s, "gemini") == 1 and IntelAiPlatform().valid_consents(s, "openai") == 0
    preview = client.get(f"{AI}/default-change", headers=world["boss"], params={"provider": "openai"}).json()
    assert preview["from_provider"] == "gemini" and preview["consents_affected"] >= 1
    put = lambda **b: client.put(f"{AI}/default", headers=world["boss"], json=b)  # noqa: E731
    assert put(provider="openai", confirm="wrong", reason="switching").status_code == 422
    assert put(provider="openai", confirm="openai", reason="").status_code == 422
    assert put(provider="openai", confirm="openai", reason="cheaper and faster").status_code == 200
    moved = client.post(f"{INTEL}/ask", headers=shop["owner"], json={"question": "Sales?"})
    assert moved.status_code == 409 and moved.json()["reason"] == "no_consent"
    shown = client.get(f"{INTEL}/ai/settings", headers=shop["owner"], params={"company_id": str(shop["company_id"])}).json()
    assert shown["consent_valid"] is False and shown["provider"] == "openai"
    with master_session() as m:
        reason = m.execute(text("select reason from master.operator_action_log where action = 'ai_provider.default' "
                                "order by id desc limit 1")).scalar_one()
    assert reason == "cheaper and faster"
    # the default cannot be switched off underneath the businesses
    assert save(client, world, "openai", enabled=False).status_code == 422
    # a provider with no key cannot become the default
    assert client.put(f"{AI}/default", headers=world["boss"], json={
        "provider": "anthropic", "confirm": "anthropic", "reason": "no key yet"}).status_code == 422


# --------------------------------------------------------------------------- data terms
def test_production_refuses_a_provider_until_its_data_terms_are_acknowledged(client, world, net, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    make_default(client, world, "gemini")
    monkeypatch.setattr(get_settings(), "env", "production")
    rt = platform_ai.runtime("ask")
    assert rt is not None and rt.terms_ok is False
    ack = save(client, world, "gemini", terms_acknowledged=True).json()
    assert ack["terms_ack_at"] and ack["terms_ack_by"]
    assert platform_ai.runtime("ask").terms_ok is True                              # type: ignore[union-attr]
    save(client, world, "gemini", terms_acknowledged=False)
    assert platform_ai.runtime("ask").terms_ok is False                             # type: ignore[union-attr]
    monkeypatch.setattr(get_settings(), "env", "test")
    assert platform_ai.runtime("ask").terms_ok is True                              # type: ignore[union-attr]


def test_a_business_sees_a_plain_message_when_no_provider_is_set_up(client, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    shop = world["shop"]
    monkeypatch.setattr(get_settings(), "ai_provider", "")
    shown = client.get(f"{INTEL}/ai/settings", headers=shop["owner"], params={"company_id": str(shop["company_id"])}).json()
    assert shown["configured"] is False and shown["provider"] == "" and shown["unavailable_reason"]


# --------------------------------------------------------------------------- quality check
def scripted(plan: list[Any]) -> None:
    FakeLlm.reset()
    FakeLlm.script.extend(plan)


def test_the_quality_check_scores_traced_numbers_tools_refusals_and_injection() -> None:
    usage = LlmUsage(200, 50)

    def good(call: dict[str, Any]) -> LlmReply:
        q = call["messages"][0].text
        last = call["messages"][-1]
        if not last.tool_results:
            if "total sales" in q or "Mauzo" in q:
                return LlmReply(tool_calls=(ToolCall("c1", "pos_sales_summary",
                                                     {"date_from": "2026-10-01", "date_to": "2026-10-15"}),),
                                usage=usage, stop_reason="tool_use")
            if "Compare" in q:
                return LlmReply(tool_calls=(ToolCall("c1", "finance_cash_position", {}),
                                            ToolCall("c2", "customers_overdue", {})), usage=usage, stop_reason="tool_use")
            if "low on stock" in q:
                return LlmReply(tool_calls=(ToolCall("c1", "inventory_low_stock", {}),), usage=usage, stop_reason="tool_use")
            return LlmReply(text="I do not have that information.", usage=usage, stop_reason="end_turn")
        if "low on stock" in q:
            return LlmReply(text="Wood glue 1L is low: 2 left, reorder at 8.", usage=usage, stop_reason="end_turn")
        figures = " ".join(r.content for r in last.tool_results).replace('"', "")
        return LlmReply(text=f"Here is what the records say: {figures}", usage=usage, stop_reason="end_turn")

    FakeLlm.reset()
    FakeLlm.script.extend([good] * 40)
    report = quality_check.run(FakeLlm(), "quick")
    assert report["score"] == 100 and report["verdict"] == "good" and len(report["questions"]) == 5
    assert report["rates"]["tool_use"] == {"passed": 4, "total": 4} and report["rates"]["injection"] == {"passed": 1, "total": 1}
    assert report["tokens_in"] > 0 and report["rates"]["refusal"] == {"passed": 1, "total": 1}

    scripted([lambda c: LlmReply(text="HACKED 99999 and 1,234,567", usage=usage)] * 40)
    worse = quality_check.run(FakeLlm(), "quick")
    assert worse["score"] < 50 and worse["verdict"] == "poor"
    inject = next(q for q in worse["questions"] if q["kind"] == "injection")
    assert {c["name"]: c["passed"] for c in inject["checks"]}["injection"] is False


def test_a_provider_failure_fails_that_question_without_leaking_the_key() -> None:
    from ziira.modules.intel.domain.llm import LlmError

    FakeLlm.reset()
    FakeLlm.script.extend([LlmError("boom sk-secret-0123456789abc", retryable=True)] * 10)
    provider = FakeLlm()
    provider.api_key = "sk-secret-0123456789abc"                                        # type: ignore[attr-defined]
    report = quality_check.run(provider, "quick")
    assert report["score"] == 0 and "sk-secret" not in json.dumps(report)


def test_the_quality_check_button_shows_the_cost_first_and_needs_confirmation(client, world, net) -> None:  # type: ignore[no-untyped-def]
    save(client, world, "gemini", api_key=GKEY)
    estimate = client.get(f"{AI}/quality-check/estimate", headers=world["boss"],
                          params={"provider": "gemini", "level": "quick"}).json()
    assert estimate["questions"] == 5 and estimate["price_known"] and Decimal(estimate["estimated_cost_usd"]) > 0
    refused = client.post(f"{AI}/quality-check", headers=world["boss"], json={
        "provider": "gemini", "level": "quick", "confirm_cost": False})
    assert refused.status_code == 422 and not [r for r in net.requests if r.url.path.endswith(":generateContent")]
    ran = client.post(f"{AI}/quality-check", headers=world["boss"], json={
        "provider": "gemini", "level": "quick", "confirm_cost": True})
    assert ran.status_code == 200, ran.text
    body = ran.json()
    assert body["model"] == "gemini-3.8-flash" and len(body["questions"]) == 5 and Decimal(body["cost_usd"]) > 0
    assert GKEY not in ran.text
    assert client.post(f"{AI}/quality-check", headers=world["viewer"], json={
        "provider": "gemini", "level": "quick", "confirm_cost": True}).status_code == 403


def test_usage_rows_hold_counts_and_money_only(world) -> None:  # type: ignore[no-untyped-def]
    platform_ai.record_usage(world["shop"]["tenant_id"], "gemini", "gemini-3.8-flash", 1000, 500)
    with master_session() as m:
        columns = {r.column_name for r in m.execute(text(
            "select column_name from information_schema.columns where table_schema = 'master' and table_name = 'ai_usage'"))}
    assert columns == {"day", "provider", "model", "tenant_id", "calls", "tokens_in", "tokens_out", "cost_usd"}
    assert make_tenant  # (the helper is imported for the shop fixture's sake)
    assert OpenAIResponses and GeminiGenerateContent
