"""Careful, read-mostly checks of the real services behind Ziira, run by hand with sandbox credentials.

    python scripts/live_check.py daraja   [--dry-run] [--phone 254708374149] [--amount 1] [--polls 6]
    python scripts/live_check.py daraja-callback --api-url http://localhost:8000 --tenant-id UUID \
                                                 --intent-id UUID --checkout-id ws_CO_... [--dry-run]
    python scripts/live_check.py sms      --to 2547XXXXXXXX [--message TEXT] [--dry-run]
    python scripts/live_check.py email    --provider smtp|brevo|resend|sendgrid --to a@b.c [--dry-run]
    python scripts/live_check.py ai       [--dry-run] [--no-tool] [--provider NAME --model ID --quality quick|full]
    python scripts/live_check.py chat     [--dry-run] [--lookup +2547XXXXXXXX]

Credentials come from the environment (see docs/live-checks.md) and are never written anywhere. Every check uses the
app's own provider classes (`ziira.plugins.mpesa.daraja`, `ziira.plugins.messaging.providers`), so a PASS means
the code that production runs works against the real service. `--dry-run` sends nothing: it feeds the same code a
made-up reply and prints the requests it would have sent, with secrets hidden, so formats can be reviewed offline.
Daraja is always used in its sandbox. Refuses to run when ZIIRA_ENV=production unless `--i-know` is given.
"""

import argparse
import contextlib
import json
import os
import secrets
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx

from ziira.modules.intel.public import LlmMessage, ToolResult, ToolSpec
from ziira.modules.intel.services import quality_check
from ziira.modules.payments.public import StkQuery, StkRequest
from ziira.plugins.ai_anthropic.provider import AnthropicMessages
from ziira.plugins.ai_gemini.provider import GeminiGenerateContent
from ziira.plugins.ai_openai.provider import OpenAIResponses
from ziira.plugins.leadsintel_platform import common as chat_common
from ziira.plugins.leadsintel_platform.provider import LeadIntelPlatformChat
from ziira.plugins.messaging.providers import (
    BlessedTextsSms,
    BrevoEmail,
    ResendEmail,
    SendGridEmail,
    SmtpEmail,
)
from ziira.plugins.mpesa import formats as mpesa
from ziira.plugins.mpesa.daraja import DarajaProvider
from ziira.sdk import ChatContext, ChatError, NotificationChannel, Outgoing, sign_value

SECRET_HEADERS = {"authorization", "api-key", "apikey", "x-api-key", "x-goog-api-key"}
SECRET_FIELDS = {"password", "api_key", "apikey", "passkey", "access_token", "consumer_secret", "consumer_key"}
HIDDEN = "***hidden***"
EMAIL_CHANNELS: dict[str, type[NotificationChannel]] = {
    "smtp": SmtpEmail, "brevo": BrevoEmail, "resend": ResendEmail, "sendgrid": SendGridEmail}


# --------------------------------------------------------------------------- hiding secrets
def hide_fields(value: Any) -> Any:
    """A copy of parsed JSON with the value of every secret-looking field hidden."""
    if isinstance(value, dict):
        return {k: HIDDEN if str(k).lower() in SECRET_FIELDS else hide_fields(v) for k, v in value.items()}
    if isinstance(value, list):
        return [hide_fields(v) for v in value]
    return value


def hide_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: HIDDEN if k.lower() in SECRET_HEADERS else v for k, v in headers.items()}


def hide_text(text: str, secret_values: list[str]) -> str:
    """`text` with any known secret value replaced (a last net for forms and error pages)."""
    for value in secret_values:
        if value and len(value) >= 4:
            text = text.replace(value, HIDDEN)
    return text


def show_body(raw: bytes, content_type: str, secret_values: list[str]) -> str:
    text = raw.decode("utf-8", "replace")
    if "json" in content_type:
        with contextlib.suppress(ValueError):
            text = json.dumps(hide_fields(json.loads(text)), indent=2)
    return hide_text(text, secret_values)[:2000]


# --------------------------------------------------------------------------- recording what is sent
@dataclass
class Exchange:
    method: str
    url: str
    headers: dict[str, str]
    request_body: str
    status: int | None = None
    response_body: str = ""


class Tap(httpx.BaseTransport):
    """Passes a request to `inner` (the network, or a made-up reply in a dry run), recording and printing both ways."""

    def __init__(self, inner: httpx.BaseTransport, secret_values: list[str], log: list[Exchange], echo: bool) -> None:
        self.inner, self.secret_values, self.log, self.echo = inner, secret_values, log, echo

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        exchange = Exchange(request.method, hide_text(str(request.url), self.secret_values),
                            hide_headers(dict(request.headers)),
                            show_body(request.content, request.headers.get("content-type", ""), self.secret_values))
        self.log.append(exchange)
        if self.echo:
            print(f"\n  --> {exchange.method} {exchange.url}")
            for name, value in exchange.headers.items():
                print(f"      {name}: {value}")
            if exchange.request_body:
                print("      " + exchange.request_body.replace("\n", "\n      "))
        response = self.inner.handle_request(request)
        response.read()
        exchange.status = response.status_code
        exchange.response_body = show_body(response.content, response.headers.get("content-type", ""),
                                           self.secret_values)
        if self.echo:
            print(f"  <-- {response.status_code}")
            if exchange.response_body:
                print("      " + exchange.response_body.replace("\n", "\n      "))
        return response


def made_up_reply(request: httpx.Request) -> httpx.Response:
    """What a dry run answers, shaped like the vendors' documented replies, so the app's code can run to the end."""
    path = request.url.path
    if "oauth" in path:
        return httpx.Response(200, json={"access_token": "dry-run-token", "expires_in": "3599"})
    if path.endswith("processrequest"):
        return httpx.Response(200, json={"MerchantRequestID": "dry-1", "CheckoutRequestID": "ws_CO_DRYRUN",
                                         "ResponseCode": "0", "ResponseDescription": "Success",
                                         "CustomerMessage": "Success. Request accepted for processing"})
    if "stkpushquery" in path:
        return httpx.Response(200, json={"MerchantRequestID": "dry-1", "CheckoutRequestID": "ws_CO_DRYRUN",
                                         "ResponseCode": "0", "ResultCode": "0", "ResultDesc": "dry run"})
    if path.endswith("/v1/messages"):
        sent = json.loads(request.content or b"{}")
        answered = any(isinstance(m.get("content"), list) and any(b.get("type") == "tool_result" for b in m["content"])
                       for m in sent.get("messages", []))
        if sent.get("tools") and not answered:
            return httpx.Response(200, json={
                "id": "msg_dry", "type": "message", "role": "assistant", "model": sent.get("model", "dry-run"),
                "stop_reason": "tool_use", "usage": {"input_tokens": 30, "output_tokens": 20},
                "content": [{"type": "tool_use", "id": "toolu_dry", "name": "echo", "input": {"text": "ping"}}]})
        return httpx.Response(200, json={
            "id": "msg_dry", "type": "message", "role": "assistant", "model": sent.get("model", "dry-run"),
            "stop_reason": "end_turn", "usage": {"input_tokens": 12, "output_tokens": 3},
            "content": [{"type": "text", "text": "OK"}]})
    if path.endswith(":generateContent"):
        sent = json.loads(request.content or b"{}")
        answered = any(p.get("functionResponse") for c in sent.get("contents", []) for p in c.get("parts", []))
        part = ({"functionCall": {"name": "echo", "args": {"text": "ping"}}} if sent.get("tools") and not answered
                else {"text": "OK"})
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [part]},
                                                         "finishReason": "STOP"}],
                                         "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 3}})
    if path.endswith("/v1/responses"):
        sent = json.loads(request.content or b"{}")
        answered = any(i.get("type") == "function_call_output" for i in sent.get("input", []))
        item = ({"type": "function_call", "call_id": "call_dry", "name": "echo", "arguments": '{"text": "ping"}'}
                if sent.get("tools") and not answered
                else {"type": "message", "content": [{"type": "output_text", "text": "OK"}]})
        return httpx.Response(200, json={"status": "completed", "model": sent.get("model", "dry-run"), "output": [item],
                                         "usage": {"input_tokens": 12, "output_tokens": 3}})
    if "leadsintel" in request.url.host:
        return httpx.Response(404, json={"error": "not_found"})        # nothing there by that id: the key was accepted
    if "blessedtexts" in request.url.host:
        return httpx.Response(200, json=[{"status_code": "1000", "status_desc": "Message Sent", "message_id": "dry"}])
    if "brevo" in request.url.host:
        return httpx.Response(201, json={"messageId": "<dry@run>"})
    if "resend" in request.url.host:
        return httpx.Response(200, json={"id": "dry-run"})
    if "sendgrid" in request.url.host:
        return httpx.Response(202, headers={"X-Message-Id": "dry-run"})
    return httpx.Response(200, json={"callback": "dry run"})


@dataclass
class Report:
    """The outcome of one check."""

    name: str
    passed: bool = False
    lines: list[str] = field(default_factory=list)
    next_step: str = ""
    exchanges: list[Exchange] = field(default_factory=list)

    def finish(self, passed: bool, next_step: str = "") -> "Report":
        self.passed, self.next_step = passed, next_step
        return self

    def print_verdict(self) -> None:
        print(f"\n{'PASS' if self.passed else 'FAIL'}  {self.name}")
        for line in self.lines:
            print(f"      {line}")
        if self.next_step:
            print(f"  Next: {self.next_step}")


def need_env(names: list[str]) -> dict[str, str]:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise SystemExit(f"Set these environment variables first (docs/live-checks.md): {', '.join(missing)}")
    return {n: os.environ[n] for n in names}


def tapped(secret_values: list[str], log: list[Exchange], dry_run: bool,
           echo: bool = True) -> Callable[[], httpx.Client]:
    inner: httpx.BaseTransport = httpx.MockTransport(made_up_reply) if dry_run else httpx.HTTPTransport()
    timeout = httpx.Timeout(20.0, connect=10.0)
    return lambda: httpx.Client(timeout=timeout, transport=Tap(inner, secret_values, log, echo))


# --------------------------------------------------------------------------- Daraja (M-Pesa)
def daraja_check(*, phone: str, amount: str, polls: int, dry_run: bool, echo: bool = True,
                 env: dict[str, str] | None = None, sleep: Callable[[float], None] = time.sleep) -> Report:
    """Token, STK push to the sandbox test number, then the query endpoint, through DarajaProvider."""
    report = Report("daraja (sandbox STK push and query)")
    env = env if env is not None else need_env([
        "ZIIRA_LIVE_DARAJA_CONSUMER_KEY", "ZIIRA_LIVE_DARAJA_CONSUMER_SECRET", "ZIIRA_LIVE_DARAJA_SHORTCODE",
        "ZIIRA_LIVE_DARAJA_PASSKEY", "ZIIRA_LIVE_DARAJA_CALLBACK_URL"])
    credentials = {"consumer_key": env["ZIIRA_LIVE_DARAJA_CONSUMER_KEY"],
                   "consumer_secret": env["ZIIRA_LIVE_DARAJA_CONSUMER_SECRET"],
                   "passkey": env["ZIIRA_LIVE_DARAJA_PASSKEY"]}
    secret_values = list(credentials.values())
    shortcode = env["ZIIRA_LIVE_DARAJA_SHORTCODE"]
    till_type = env.get("ZIIRA_LIVE_DARAJA_TILL_TYPE", "paybill")
    provider = DarajaProvider()
    provider.client_factory = tapped(secret_values, report.exchanges, dry_run, echo)
    DarajaProvider._tokens.clear()
    print("Step 1-2: OAuth token, then the STK push (the sandbox test number gets no real prompt).")
    try:
        response = provider.stk_push(StkRequest(
            shortcode=shortcode, settings={"till_type": till_type}, amount=Decimal(amount),
            msisdn=mpesa.normalize_phone(phone),
            callback_url=env["ZIIRA_LIVE_DARAJA_CALLBACK_URL"], account_reference="ZIIRA-CHECK",
            description="Live check", credentials=credentials, environment="sandbox"))
    except httpx.HTTPError as exc:
        return report.finish(False, f"Safaricom was unreachable or failing ({exc}). Check the network "
                                    "and Safaricom's status page, then run again.")
    report.lines.append(f"push accepted={response.accepted} request id={response.provider_request_id} "
                        f"message={response.message!r}")
    if not response.accepted:
        step = ("Safaricom refused the credentials: re-copy the consumer key and secret of the sandbox app (not a "
                "production app)." if "credentials" in response.message else
                "Read the message above. Typical causes: wrong shortcode or passkey (use the Lipa Na M-Pesa Online "
                "test values on the portal), an unreachable or non-HTTPS callback URL, or an amount of 0.")
        return report.finish(False, step)
    print("\nStep 3: ask the query endpoint what became of it.")
    result = None
    for attempt in range(max(polls, 1)):
        try:
            result = provider.query_stk(StkQuery(shortcode=shortcode, provider_request_id=str(
                response.provider_request_id), credentials=credentials, environment="sandbox"))
        except httpx.HTTPError as exc:
            return report.finish(False, f"The query endpoint failed ({exc}). Run again; if it repeats, compare "
                                        "its reply above with query_stk in ziira/modules/payments/providers.py.")
        report.lines.append(f"query {attempt + 1}: code={result.result_code} description={result.description!r}")
        if result.result_code != -1:
            break
        if not dry_run and attempt + 1 < polls:
            sleep(5)
    assert result is not None
    if result.result_code == -1:
        report.lines.append("still pending after the last poll; the shape of the reply was understood")
    return report.finish(True, "If the sandbox simulator shows the prompt, confirm or cancel it and run "
                               "`daraja-callback` to test our callback endpoint. Then tick the Daraja item in "
                               "docs/go-live-checklist.md only when C2B and the callbacks have also been tried.")


def stk_callback_body(checkout_id: str, amount: str, phone: str, receipt: str) -> dict[str, Any]:
    """A callback body as Safaricom documents it for a successful prompt."""
    return {"Body": {"stkCallback": {
        "MerchantRequestID": "live-check", "CheckoutRequestID": checkout_id, "ResultCode": 0,
        "ResultDesc": "The service request is processed successfully.",
        "CallbackMetadata": {"Item": [
            {"Name": "Amount", "Value": float(amount)}, {"Name": "MpesaReceiptNumber", "Value": receipt},
            {"Name": "TransactionDate", "Value": int(time.strftime("%Y%m%d%H%M%S"))},
            {"Name": "PhoneNumber", "Value": int(phone)}]}}}}


def signed_callback_url(api_url: str, tenant_id: uuid.UUID, intent_id: uuid.UUID) -> str:
    """The same address the app gives Safaricom for a prompt (services/intents.py: callback_url), for the given API."""
    return (f"{api_url.rstrip('/')}/api/v1/payments/callbacks/stk/{tenant_id.hex}/{intent_id}/"
            f"{sign_value(f'stk:{intent_id}')}")


def callback_check(*, api_url: str, tenant_id: str, intent_id: str, checkout_id: str, amount: str, phone: str,
                   dry_run: bool, echo: bool = True) -> Report:
    """Post a sample success callback to our own API and show the intent it settled. Needs the intent to exist (start
    an M-Pesa prompt in the app against a sandbox account first; its id and checkout id are on the intent)."""
    report = Report("daraja callback (our endpoint, signed address)")
    url = signed_callback_url(api_url, uuid.UUID(tenant_id), uuid.UUID(intent_id))
    receipt = "LC" + secrets.token_hex(4).upper()
    body = stk_callback_body(checkout_id, amount, mpesa.normalize_phone(phone), receipt)
    client = httpx.Client(timeout=20, transport=Tap(httpx.MockTransport(made_up_reply) if dry_run else
                                                    httpx.HTTPTransport(), [], report.exchanges, echo))
    shown = url.rsplit("/", 1)[0] + "/" + HIDDEN
    print(f"Posting a sample callback (receipt {receipt}) to {shown}")
    try:
        response = client.post(url, json=body)
    except httpx.HTTPError as exc:
        return report.finish(False, f"Could not reach {api_url} ({exc}). Is the API running and is the address right?")
    report.lines.append(f"callback answered {response.status_code}")
    if response.status_code == 404:
        return report.finish(False, "404 means a wrong signature or tenant. The check must run with the same "
                                    "ZIIRA_SECRET_KEY as the API, and the tenant id and intent id must match.")
    if response.status_code != 200:
        return report.finish(False, f"Unexpected status {response.status_code}; read the API log.")
    if dry_run:
        return report.finish(True, "Dry run only: nothing was sent.")
    token = os.environ.get("ZIIRA_LIVE_API_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {"X-Tenant-ID": tenant_id}
    intent = httpx.get(f"{api_url.rstrip('/')}/api/v1/payments/intents/{intent_id}", headers=headers, timeout=20)
    if intent.status_code != 200:
        report.lines.append(f"could not read the intent ({intent.status_code}); set ZIIRA_LIVE_API_TOKEN")
        return report.finish(True, "The endpoint accepted the callback; look at the intent in the app to confirm "
                                   "it shows the receipt and status 'succeeded'.")
    data = intent.json()
    report.lines.append(f"intent status={data.get('status')} receipt={data.get('receipt')} "
                        f"result_code={data.get('result_code')}")
    ok = data.get("status") == "succeeded" and data.get("receipt") == receipt
    return report.finish(ok, "" if ok else "The endpoint answered but the intent did not settle. It may already have "
                                          "been final (a callback is applied once), or its id is wrong: use a fresh "
                                          "pending prompt.")


# --------------------------------------------------------------------------- SMS and email
def explain_refusal(message: str) -> str:
    low = message.lower()
    if any(w in low for w in ("key", "auth", "credential")):
        return "The provider refused the API key. Copy it again from the provider's dashboard."
    if any(w in low for w in ("sender", "from", "domain", "verified")):
        return "The sender is not approved or verified. Approve/verify it in the provider's dashboard first."
    if any(w in low for w in ("balance", "credit", "fund")):
        return "The account has no credit. Top it up."
    return "Read the provider's own words above, fix what they name, and run again."


def send_check(channel: NotificationChannel, message: Outgoing, secret: dict[str, Any],
               config: dict[str, Any], report: Report) -> Report:
    try:
        result = channel.send(message, secret, config)
    except httpx.HTTPError as exc:
        return report.finish(False, f"The service was unreachable or failing ({exc}); this is retried in the app. "
                                    "Check the network, then run again.")
    except OSError as exc:
        return report.finish(False, f"Could not connect ({exc}). Check host, port and network.")
    report.lines.append(f"accepted={result.accepted} provider_ref={result.provider_ref} message={result.message!r} "
                        f"permanent_failure={result.permanent_failure}")
    if result.accepted:
        return report.finish(True, f"Check that the message really arrived at {message.recipient}. If it did not, "
                                   "look at the provider's delivery log.")
    return report.finish(False, explain_refusal(result.message or ""))


def sms_check(*, to: str, text: str, dry_run: bool, echo: bool = True, env: dict[str, str] | None = None) -> Report:
    report = Report("sms (BlessedTexts)")
    env = env if env is not None else need_env(["ZIIRA_LIVE_SMS_API_KEY", "ZIIRA_LIVE_SMS_SENDER_ID"])
    channel = BlessedTextsSms()
    channel.client_factory = tapped([env["ZIIRA_LIVE_SMS_API_KEY"]], report.exchanges, dry_run, echo)   # type: ignore[misc]
    message = Outgoing(uuid.uuid4(), uuid.uuid4(), to, None, text)
    return send_check(channel, message, {"api_key": env["ZIIRA_LIVE_SMS_API_KEY"]},
                      {"sender_id": env["ZIIRA_LIVE_SMS_SENDER_ID"]}, report)


class RecordingSmtp:
    """Stands in for smtplib in a dry run: records what would be said to the server."""

    def __init__(self, log: list[Exchange]) -> None:
        self.log = log

    def __call__(self, host: str, port: int, **_: Any) -> "RecordingSmtp":
        self.log.append(Exchange("SMTP", f"{host}:{port}", {}, ""))
        return self

    def __enter__(self) -> "RecordingSmtp":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def starttls(self, **_: Any) -> None:
        self.log[-1].headers["starttls"] = "yes"

    def login(self, user: str, _password: str) -> None:
        self.log[-1].headers["login"] = f"{user} / {HIDDEN}"

    def send_message(self, email: Any) -> None:
        self.log[-1].request_body = "\n".join(f"{k}: {v}" for k, v in email.items()) + "\n\n" + email.get_content()


def email_check(*, provider: str, to: str, dry_run: bool, echo: bool = True,
                env: dict[str, str] | None = None) -> Report:
    report = Report(f"email ({provider})")
    names = ["ZIIRA_LIVE_EMAIL_FROM_ADDRESS"] + (
        ["ZIIRA_LIVE_SMTP_HOST", "ZIIRA_LIVE_SMTP_USERNAME", "ZIIRA_LIVE_SMTP_PASSWORD"] if provider == "smtp"
        else ["ZIIRA_LIVE_EMAIL_API_KEY"])
    env = env if env is not None else need_env(names)
    channel = EMAIL_CHANNELS[provider]()
    config: dict[str, Any] = {"from_address": env["ZIIRA_LIVE_EMAIL_FROM_ADDRESS"],
                              "from_name": env.get("ZIIRA_LIVE_EMAIL_FROM_NAME", "Ziira live check")}
    if provider == "smtp":
        secret: dict[str, Any] = {
            "host": env["ZIIRA_LIVE_SMTP_HOST"], "port": int(env.get("ZIIRA_LIVE_SMTP_PORT", "587")),
            "username": env["ZIIRA_LIVE_SMTP_USERNAME"], "password": env["ZIIRA_LIVE_SMTP_PASSWORD"]}
        if dry_run:
            recorder = RecordingSmtp(report.exchanges)
            channel.smtp_factory = recorder        # type: ignore[attr-defined]
            channel.smtp_ssl_factory = recorder    # type: ignore[attr-defined]
    else:
        secret = {"api_key": env["ZIIRA_LIVE_EMAIL_API_KEY"]}
        channel.client_factory = tapped([secret["api_key"]], report.exchanges, dry_run, echo)   # type: ignore[attr-defined]
    message = Outgoing(uuid.uuid4(), uuid.uuid4(), to, "Ziira live check", "A test message from Ziira's live check.")
    result = send_check(channel, message, secret, config, report)
    if provider == "smtp" and dry_run and echo:
        for ex in report.exchanges:
            print(f"\n  --> {ex.method} {ex.url} {ex.headers}\n      " + ex.request_body.replace("\n", "\n      "))
    return result


# --------------------------------------------------------------------------- AI provider (Anthropic Messages API)
AI_PROVIDERS: dict[str, Any] = {"anthropic": AnthropicMessages, "gemini": GeminiGenerateContent,
                                "openai": OpenAIResponses}


def ai_check(*, dry_run: bool, tool_step: bool = True, echo: bool = True, env: dict[str, str] | None = None,
             provider_name: str = "anthropic", model: str | None = None, quality: str | None = None) -> Report:
    """A harmless prompt through the app's own provider class (`provider_name`), then (unless `tool_step` is off) a
    tool-use round trip with a made-up `echo` tool: the part of the request/response mapping most worth confirming.
    With `quality` ("quick" or "full") it then asks the fixed business questions (English and Swahili, a tool-using
    one, a refusal to invent, an injection attempt) and prints a scored report with the estimated cost: real spend."""
    report = Report(f"ai ({provider_name})")
    if env is None:
        env = {"ZIIRA_LIVE_AI_API_KEY": "dry-run-key-not-used"} if dry_run else need_env(["ZIIRA_LIVE_AI_API_KEY"])
    key = env["ZIIRA_LIVE_AI_API_KEY"]
    kwargs: dict[str, Any] = {"api_key": key, "max_retries": 0}
    if model or env.get("ZIIRA_LIVE_AI_MODEL"):
        kwargs["model"] = model or env["ZIIRA_LIVE_AI_MODEL"]
    if env.get("ZIIRA_LIVE_AI_BASE_URL"):
        kwargs["base_url"] = env["ZIIRA_LIVE_AI_BASE_URL"]
    provider = AI_PROVIDERS[provider_name](**kwargs)
    factory = tapped([key], report.exchanges, dry_run, echo)
    provider.client_factory = lambda _timeout: factory()
    print(f"Step 1: one harmless prompt to model {provider.model_id()}.")
    try:
        first = provider.complete([LlmMessage("user", "Reply with the single word OK.")], [], "", 20)
    except Exception as exc:  # noqa: BLE001 - the verdict names it
        return report.finish(False, explain_ai_failure(str(exc)))
    report.lines.append(f"reply={first.text!r} stop_reason={first.stop_reason} model={first.model} "
                        f"tokens={first.usage.input_tokens}+{first.usage.output_tokens}")
    if not first.text.strip():
        return report.finish(False, "The reply was empty. Read the exchange above: is the model id right?")
    if tool_step:
        print("Step 2: a tool-use round trip with a made-up echo tool.")
        echo_tool = ToolSpec("echo", "Returns the text it is given.", {
            "type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]})
        ask = LlmMessage("user", "Call the echo tool with the text 'ping', then tell me what it returned.")
        try:
            asked = provider.complete([ask], [echo_tool], "", 200)
            if not asked.tool_calls:
                return report.finish(False, "The model did not call the tool. Read the exchange above; the tool "
                                            "definition format may need a change in the provider.")
            call = asked.tool_calls[0]
            report.lines.append(f"tool call: {call.name}({call.arguments}) stop_reason={asked.stop_reason}")
            done = provider.complete([ask, LlmMessage("assistant", asked.text, tool_calls=asked.tool_calls),
                                      LlmMessage("user", tool_results=(ToolResult(call.id, "ping"),))],
                                     [echo_tool], "", 200)
        except Exception as exc:  # noqa: BLE001
            return report.finish(False, explain_ai_failure(str(exc)))
        report.lines.append(f"final reply={done.text!r} stop_reason={done.stop_reason}")
        if not done.text.strip():
            return report.finish(False, "No final text after the tool result. Read the exchange above.")
    if quality:
        print(f"Step 3: the {quality} quality check (real requests; this costs money).")
        scored = quality_check.run(provider, quality)
        catalog = provider.catalog()
        info = catalog.model(provider.model_id()) if catalog else None
        cost = (info.input_per_mtok * scored["tokens_in"] + info.output_per_mtok * scored["tokens_out"]) / 1_000_000 \
            if info else None
        for q in scored["questions"]:
            marks = " ".join(f"{'ok' if c['passed'] else 'FAIL'}:{c['name']}" for c in q["checks"])
            report.lines.append(f"[{q['id']}] {marks} ({q['latency_ms']} ms)")
        report.lines.append(f"score={scored['score']} verdict={scored['verdict']} rates={scored['rates']} "
                            f"avg_latency_ms={scored['latency_ms_average']} tokens={scored['tokens_in']}+"
                            f"{scored['tokens_out']} estimated_cost_usd={'unknown' if cost is None else f'{cost:.4f}'}")
        return report.finish(scored["score"] >= 75, "Compare the models by their scores and cost before switching "
                                                    "(Super Admin > AI).")
    return report.finish(True, "Compare the exchange above with the provider's API reference; then save the key in "
                               "Super Admin > AI. Nothing was stored.")


def explain_ai_failure(message: str) -> str:
    low = message.lower()
    if "401" in low or "authentication" in low:
        return "The provider refused the API key. Copy it again from the provider's console."
    if "404" in low or "model" in low:
        return "The model id may be wrong (set ZIIRA_LIVE_AI_MODEL to a model your account can use)."
    if "429" in low or "529" in low or "overloaded" in low:
        return "The provider is rate limiting or busy. Wait and run again."
    return "Read the provider's own words above, fix what they name, and run again."


# --------------------------------------------------------------------------- the platform chat bot (Lead Intel)
def chat_check(*, dry_run: bool, lookup: str | None, echo: bool = True, env: dict[str, str] | None = None) -> Report:
    """Read-only checks of the platform chat bot's Lead Intel code: does the key work (a harmless read of a request
    that does not exist), can a number be looked up (optional), and does the signature check accept a delivery signed
    the documented way. It never connects, changes or sends anything. The key is read from the environment and never
    written anywhere."""
    report = Report("chat (Lead Intel key, lookup and signature)")
    if env is None:
        env = {"ZIIRA_LIVE_LEADSINTEL_KEY": "dry-run-key"} if dry_run else need_env(["ZIIRA_LIVE_LEADSINTEL_KEY"])
    key = env["ZIIRA_LIVE_LEADSINTEL_KEY"]
    factory = tapped([key], report.exchanges, dry_run, echo)
    ctx = ChatContext(config={}, secrets={"api_key": key}, http=factory())
    provider = LeadIntelPlatformChat()
    print("Step 1: the key (GET of a request that cannot exist; 404 means the key was accepted).")
    try:
        verdict = provider.test_key(ctx)
    except ChatError as exc:
        return report.finish(False, explain_chat_failure(exc.code))
    report.lines.append(f"key accepted={verdict.ok}: {verdict.message}")
    if not verdict.ok:
        return report.finish(False, "Copy the platform key again from Lead Intel (Settings > Developers).")
    if lookup:
        print("Step 2: look the number up (read only).")
        digits = "".join(c for c in lookup if c.isdigit())
        try:
            found = provider.find_connection(ctx, digits[:3], digits[3:])
        except ChatError as exc:
            return report.finish(False, explain_chat_failure(exc.code))
        report.lines.append("no connection found for that number" if found is None else
                            f"connection found: active={found.active} status={found.status}")
    print("Step 3: a delivery signed the documented way is accepted, a tampered one is refused (no network).")
    secret, stamp = "live-check-secret", str(int(time.time() * 1000))
    raw = json.dumps({"metadata": {"phone_number_id": "1"}, "messages": [
        {"id": "wamid.check", "from": "10000000000", "type": "text", "text": {"body": "hello"}}]}).encode()
    headers = {"x-leadintel-event-id": "check-1", "x-leadintel-timestamp": stamp,
               "x-leadintel-signature": chat_common.signature_of(secret, stamp, raw)}
    delivery = chat_common.read_delivery(headers, raw, secret, "1")
    report.lines.append(f"signed delivery read: {len(delivery.messages)} message(s)")
    try:
        chat_common.read_delivery(headers, raw + b" ", secret, "1")
        return report.finish(False, "A tampered body was accepted: do not go live.")
    except Exception:  # noqa: BLE001 - the refusal is the point
        report.lines.append("tampered body refused")
    return report.finish(True, "Now follow docs/ai.md section 15 (Going live): connect a number you can lose, send it "
                               "a message, and check the reply arrives. Nothing was changed here.")


def explain_chat_failure(code: str) -> str:
    return {"key_rejected": "Lead Intel refused the key. Copy it again from your Lead Intel account.",
            "rate_limited": "Lead Intel is rate limiting. Wait a minute and run again.",
            "unavailable": "Lead Intel could not be reached. Check your connection and try again."}.get(
        code, "Read Lead Intel's own words above, fix what they name, and run again.")


# --------------------------------------------------------------------------- command line
def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--i-know", action="store_true", help="allow running with ZIIRA_ENV=production")
    sub = p.add_subparsers(dest="check", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--dry-run", action="store_true", help="print the requests, send nothing")

    d = sub.add_parser("daraja")
    common(d)
    d.add_argument("--phone", default="254708374149", help="the sandbox test number")
    d.add_argument("--amount", default="1")
    d.add_argument("--polls", type=int, default=6, help="how many times to ask the query endpoint (5 s apart)")
    c = sub.add_parser("daraja-callback")
    common(c)
    c.add_argument("--api-url", default="http://localhost:8000")
    c.add_argument("--tenant-id", required=True)
    c.add_argument("--intent-id", required=True)
    c.add_argument("--checkout-id", required=True)
    c.add_argument("--amount", default="1")
    c.add_argument("--phone", default="254708374149")
    s = sub.add_parser("sms")
    common(s)
    s.add_argument("--to", required=True, help="a number you control, in the format your gateway expects")
    s.add_argument("--message", default="Ziira live check: if you can read this, SMS works.")
    e = sub.add_parser("email")
    common(e)
    e.add_argument("--provider", required=True, choices=sorted(EMAIL_CHANNELS))
    e.add_argument("--to", required=True)
    a = sub.add_parser("ai", help="one harmless prompt, and a tool-use round trip, through the AI provider code")
    common(a)
    a.add_argument("--no-tool", action="store_true", help="only the plain prompt, no tool-use round trip")
    a.add_argument("--provider", default="anthropic", choices=sorted(AI_PROVIDERS))
    a.add_argument("--model", help="a model id (default: the plugin's recommended Ask model)")
    a.add_argument("--quality", choices=["quick", "full"], help="then run the scored quality check (real spend)")
    ch = sub.add_parser("chat", help="the platform chat bot through Lead Intel: key, lookup and signature (read only)")
    common(ch)
    ch.add_argument("--lookup", help="also look this number up, in international form (+2547...), read only")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if os.environ.get("ZIIRA_ENV", "").lower() == "production" and not args.i_know:
        print("Refusing to run: ZIIRA_ENV=production. These checks are for sandboxes; pass --i-know to override.")
        return 2
    if args.check == "daraja":
        report = daraja_check(phone=args.phone, amount=args.amount, polls=args.polls, dry_run=args.dry_run)
    elif args.check == "daraja-callback":
        report = callback_check(api_url=args.api_url, tenant_id=args.tenant_id, intent_id=args.intent_id,
                                checkout_id=args.checkout_id, amount=args.amount, phone=args.phone,
                                dry_run=args.dry_run)
    elif args.check == "ai":
        report = ai_check(dry_run=args.dry_run, tool_step=not args.no_tool, provider_name=args.provider,
                          model=args.model, quality=args.quality)
    elif args.check == "chat":
        report = chat_check(dry_run=args.dry_run, lookup=args.lookup)
    elif args.check == "sms":
        report = sms_check(to=args.to, text=args.message, dry_run=args.dry_run)
    else:
        report = email_check(provider=args.provider, to=args.to, dry_run=args.dry_run)
    report.print_verdict()
    if args.dry_run:
        print("\n  DRY RUN: nothing was sent and the replies above are made up. This proves the request format only.")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
