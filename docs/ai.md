# The AI layer: explanations, ranking and Ask Ziira

The AI layer of Ziira Intelligence (`ziira/modules/intel`, spec section 16). A language model writes **sentences**; it never
supplies **figures**. Every number a person sees comes from a check or a query over the business's own records, and a reply
whose numbers cannot be traced back to those records is discarded or marked.

> **Not run against the real service.** The Anthropic, Gemini and OpenAI request and response shapes (`ziira/plugins/ai_*/provider.py`)
> were written from the providers' public documentation (section 12 lists what is unverified). Everything is tested against a scripted fake provider and a pretend
> HTTP server; nothing has been sent to the live API. Run `scripts/live_check.py ai` (section 10) with a real key before
> turning this on for a customer.

It is **off for every business** until an Owner consents (section 2).

## 1. What it does

| Feature | Where | How |
|---|---|---|
| **Explanation** of a finding | Finding page ("AI-written" card, **Write again** for managers); optional background job | The model is given the finding's summary, action, figures and record labels and writes 2-4 plain sentences. Stored in `intel.finding.explanation_ai`, separate from `explanation` (what a person said). |
| **Ranking** of the top findings | Command Center "needs attention" list, daily and weekly briefs | The model orders the 12 most pressing open findings with a one-line reason each. Used while fresh (12 h); falls back to `rank_score`. |
| **Ask Ziira** | Command Center panel; `POST /api/v1/intel/ask` | A question in English or Swahili. The model may only call **tools** that units offer over their own data (`intel.ask_tool`), as the person asking. |

It does not act: no tool writes anything, and nothing involving money changes (action levels 3 and 4 are still not built).

## 2. Consent, switching on and off

Company settings that change only through the screen **Settings > AI assistant** or `PUT /api/v1/intel/ai/settings` (permission
`ai.manage`, Owner only), not through the general settings endpoint:

| Setting | Default | Meaning |
|---|---|---|
| `ai_enabled` | `false` | The assistant is on. Works only together with a valid consent record: the setting alone does nothing. |
| `ai_explanations` | `true` | With it on: explanations and ranking. |
| `ai_auto_explain` | `false` | With it on: new findings of medium severity or worse are explained in the background (5 per run, every 15 minutes; a failed try waits 6 hours). |
| `ai_ask` | `true` | With it on: people with `ai.ask` may use Ask Ziira. |
| `ai_monthly_token_limit` | 2,000,000 | Tokens (input + output) per calendar month (UTC) per company. When used >= limit every call is refused (`budget`) until next month or until raised; each call is also asked for no more than what is left. |

Switching on needs the **current consent text accepted**: the request carries `accept_version` (the `consent_version` the screen
showed) and the language read. A row is written to `intel.ai_consent` (immutable: who, when, language, the exact text, its hash, the
provider and model). Switching off writes a `revoked` row, flips `ai_enabled`, and **every later call, including one in progress
between two model rounds, is refused**. The consent is valid only for the text version and the provider it was given for: a new
text version or a different `ZIIRA_AI_PROVIDER` makes it invalid until an Owner agrees again.

Permissions (intel manifest): `ai.manage` (Owner only) and `ai.ask` (Owner, Finance Manager, Branch Manager, Accountant).

## 3. What is sent to the provider, and what is not

Sent: the finding's summary, recommended action, severity, area, period, amount, the figures the check computed and the **labels** of
its records ("Product CEM"); for Ask Ziira, the question and the bounded results of the tools it called (totals, counts, balances,
product and branch names, branch ids the person may use).

Never sent: phone numbers, email addresses, tax numbers, bank details, national ids, passwords, keys, salaries (no tool offers pay
or payroll). Two layers:

1. **Names of people become labels.** Customers, suppliers, employees and users appear as `Customer A`, `Employee B`, `Person C`
   (`Pseudonyms`, `domain/ai_rules.py`). The names come from the records behind a finding, from tool result fields a tool lists in
   `personal_fields`, and from every login name in the business. The labels hold no digits, so they never count as figures, and they
   are replaced by the real names again in the reply the person sees. The conversation store holds the real names (the person sees
   their own rows).
2. **A scrub of everything sent** (`scrub_personal`): email addresses, phone numbers (with `+`, or separated groups of 9+ digits),
   runs of 9+ digits, and mixed letter-and-digit identifiers of 9+ characters become `[email]`, `[phone]`, `[number]`, `[id]`. Money
   with separators and dates are left alone. It is a best-effort net: free text typed by staff that names a person who has no login
   and no record in the finding is not recognised. Tools should not return free text.

What a person types in a question is sent as written (after the scrub): a customer's name typed into a question reaches the provider
as typed, because only names the system already knows are replaced.

The system prompts, the rules the model is given and the tool descriptions are in `services/explain.py` and `services/ask.py`.

## 4. How the answers are checked

- **Explanations** (strict): every number in the reply must appear in the facts sent (`FigureChecker(strict=True)`). Otherwise the reply
  is discarded (`422 ai_rejected`, call log status `rejected`) and the finding keeps its deterministic text. Also discarded: empty,
  cut short (`max_tokens`), over 1,500 characters.
- **Ranking**: the reply must be JSON that is **exactly a permutation** of the ids sent (F1..Fn), each with a one-line reason whose
  numbers are in the facts. Anything else leaves the old order. A stored order is used for 12 hours; it only reorders the findings it
  ranked, in the places they already hold, so a finding that appeared since keeps its deterministic place.
- **Ask Ziira** (looser, because the person asked for an analysis): every number in the answer must be in the tool results or the
  question or today's date, or be a **rounding** of one ("1.2 million", "12.3%"), a **sum or difference of two**, a **share** of one in
  another (only with a % sign), the **count of rows**, or the **total / average / running total of a column** of rows. Otherwise the
  answer is kept, **"Some figures could not be verified against your data."** is appended (Swahili in Swahili), and the message is
  `flagged` with the offending numbers. Weakness: with many figures in play a small integer can match a derived value by chance; the
  sources are always shown so a person can check.
- **Tool use**: arguments are checked against the tool's JSON schema (unknown keys dropped, types, bounds, ISO dates, uuids). A tool
  the person cannot use is not offered, and if the model names one anyway (or one that does not exist) it is refused. At most 4 tool
  calls per round, **6 rounds**, 40,000 tokens and 75 seconds per question; after a cap the model is asked once more without tools and
  must answer with what it has (`capped` says which cap), or a plain fallback is returned and flagged.
- The model gets no memory of earlier questions: each question stands alone (the page keeps the conversation together for reading).

## 5. What is stored

| Table | Holds | Kept |
|---|---|---|
| `intel.ai_consent` | Who agreed or withdrew, when, language, the exact text, hash, provider, model. Immutable. | Always (it is the proof of consent). |
| `intel.ai_usage` | Tokens and calls per company and month. | Always. |
| `intel.ai_call_log` | Every call **and every refusal**: who asked, purpose, finding or `intel.ask`, provider, model, **a SHA-256 of what was sent**, tools called (name and the names of the arguments, not their values), tokens, latency, outcome, short error text with any key removed. Never the prompt, never the reply, never a key. | 400 days (`intel.purge_ai_history`). |
| `intel.ask_session` / `ask_message` | A person's conversation: questions, answers, the tools called and the rows they returned, flags. Visible to that person and to `ai.manage` holders for audit (`GET /ask/sessions?everyone=true`). | 90 days after the last message. |
| `intel.ai_ranking` | The model's last ordering and reasons per company. | Replaced each run. |
| `intel.finding.explanation_ai` | The AI-written text, `explanation_ai_at`, `explanation_ai_tried_at`. | With the finding. |

An API key is a **platform** secret (`ZIIRA_AI_API_KEY`): it is never stored in a tenant database, a log row, an audit entry or an
error message (the provider code removes it and anything shaped like a key before an error is stored; tested with Hypothesis).

## 6. Where the model is called from

Never inside a database transaction. `ai.call` opens a short transaction to check consent, budget and settings, **closes it**, calls
the provider, then opens another to record usage and the log. Ask Ziira and "Write again" run in the request thread with bounded time
(a provider call has a 30 s timeout and 2 retries; the question has the caps above); the background work uses
`@unbound_periodic` (`ziira/kernel/jobs.py`), recurring tasks that the worker runs with no transaction open:

| Task | Every | Does |
|---|---|---|
| `intel.ai_explain` | 15 min | Explains up to 5 new findings per company that have `ai_auto_explain` on. |
| `intel.ai_rank` | 2 h | Asks for an ordering of each company's top findings (needs at least 3). |
| `intel.purge_ai_history` | 1 day | Forgets old call-log rows and conversations. |

Run by hand: `ziira run-task <tenant> intel.ai_explain` (also `intel.ai_rank`).

## 7. The provider contract (`intel.llm`)

```python
class LlmProvider(ABC):          # ziira.modules.intel.public
    name: str                    # what ZIIRA_AI_PROVIDER selects
    label: str                   # shown in the consent text
    def configured(self) -> bool: ...        # the platform has what it needs (its key)
    def model_id(self) -> str: ...
    def complete(self, messages, tools, system, max_tokens) -> LlmReply: ...   # raises LlmError(retryable=...)
```

A conversation is a list of `LlmMessage` (user text; assistant text with `tool_calls`; a user turn carrying `tool_results`), tools are
`ToolSpec(name, description, JSON schema)`, and the reply is `LlmReply(text, tool_calls, usage, stop_reason, model)`. A provider
implements `complete` in a plugin (`@provides("intel.llm")`) and is chosen by name; it must retry its own transient failures, never
log a prompt or a key, and be called only with no transaction open (the gateway guarantees that).

Platform settings (environment): `ZIIRA_AI_PROVIDER` (`anthropic`), `ZIIRA_AI_API_KEY`, `ZIIRA_AI_MODEL` (`claude-sonnet-5-5`),
`ZIIRA_AI_BASE_URL`, `ZIIRA_AI_TIMEOUT_SECONDS` (30), `ZIIRA_AI_MAX_RETRIES` (2), `ZIIRA_AI_TERMS_CONFIRMED`. In production no start-up
check needs the key (it is needed only if some business switches the assistant on: without it the screen says the platform has no
provider, and nothing is sent); calls are refused until `ZIIRA_AI_TERMS_CONFIRMED=true`; the `fake` provider is refused.

**Anthropic plugin** (`ziira/plugins/ai_anthropic`): `POST {base}/v1/messages` with `x-api-key`, `anthropic-version: 2023-06-01`;
body `{model, max_tokens, system?, messages, tools?}`; `tool_use` / `tool_result` content blocks; 429, 529 and 5xx retried with growing
pauses (`Retry-After` respected up to 20 s), 4xx refused at once; input tokens include cache read/creation tokens. It needs no
per-business enabling: the platform chooses the provider.

**`FakeLlm`** (`ziira/modules/intel/fake_llm.py`, `ZIIRA_AI_PROVIDER=fake`, refused in production): scripted replies and tool calls for
tests and local work (`FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", {...}), FakeLlm.say("...")])`, calls kept in
`FakeLlm.calls`).

## 8. Adding an ask tool

In the unit that owns the data (its manifest lists `"intel"` under `optional` and `"intel.ask_tool"` under `[extends] implements`),
a file such as `ziira/modules/<unit>/ask_tools.py`, imported at the end of `hooks.py`:

```python
@provides(INTEL_ASK_TOOL)
class LowStock(AskTool):
    name = "inventory_low_stock"                          # "<unit>_<what>", unique
    description = "Products at or below their reorder level at each branch, the most short first."
    parameters = {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 30}}}
    permissions = ("stock.view",)                          # any-of: who is offered the tool
    personal_fields = ()                                   # result keys holding a person's name ("customer", "employee")

    def run(self, session, context, params):               # params also has company_id, set by Ask Ziira
        scope = branch_scope(context, ("stock.view",), UUID(params["company_id"]))   # which branches this person may see
        branch = requested_branch(scope, params)           # refuses a branch they may not see
        clause, values = scope.sql("o.branch_id")
        ...                                                # read-only SQL over YOUR tables, bounded (limit), no free text in SQL
        return {"rows": [...], "note": "Only branches you may see are included."}
```

Rules: read only; filter **every** query by the asker's scope (`branch_scope`, `company_visible`, or call a report service that already
does); never return phone numbers, emails, tax ids, bank details or pay; money and quantities as strings; at most a few dozen rows
(Ask Ziira cuts lists at 40 rows); keys ending in `_id` are ignored when checking figures; test it with a branch manager of another
branch (`tests/test_ai_layer.py::test_every_tool_filters_by_branch_for_a_branch_manager`). Tools shipped: findings (list, detail),
Command Center figures, sales (summary, top products, voids), customers (balance, overdue), stock (on hand, low), suppliers (balance,
bills due), finance (profit and loss, cash position), people (headcount, leave waiting).

## 9. The data-terms requirement

Business data goes to the AI provider only under terms that say **customer data sent through the API is not used to train the
provider's models** and say how long it is kept. Ziira's consent text promises this. Before any business switches the assistant on in
production the operator must (a) have those terms in place with the provider (for Anthropic: the commercial terms and, where
personal data is involved, a data processing agreement; check the current text, this repository cannot), (b) list the provider as a
sub-processor in the DPA checklist (`docs/privacy.md` section 8), and (c) set `ZIIRA_AI_TERMS_CONFIRMED=true`. Until then production refuses every call.

## 10. Operating it

1. Apply the migration to existing businesses: `ziira install --all` (intel `0003_ai`). New permissions reach the Owner by the same upgrade.
2. Check the request format: `set -a; . ./.env; set +a; export ZIIRA_LIVE_AI_API_KEY=...`, then
   `.venv/bin/python scripts/live_check.py ai --dry-run` (prints the requests, key hidden) and then
   `.venv/bin/python scripts/live_check.py ai` (a harmless prompt, then a tool-use round trip with a made-up `echo` tool;
   `--no-tool` for the prompt only; optional `ZIIRA_LIVE_AI_MODEL`, `ZIIRA_LIVE_AI_BASE_URL`). Details in `docs/live-checks.md`.
3. Set `ZIIRA_AI_API_KEY`, `ZIIRA_AI_TERMS_CONFIRMED=true`; restart the API and `ziira worker`.
4. An Owner opens Settings > AI assistant, reads the text, agrees. Watch the request log on the same screen in the first days.

API (all under `/api/v1/intel`): `GET /ai/status` (anyone who uses it), `GET|PUT /ai/settings`, `GET /ai/calls` (`ai.manage`),
`POST /ask`, `GET /ask/sessions`, `GET /ask/sessions/{id}` (`ai.ask`), `POST /findings/{id}/ai-explanation` (`findings.manage`).
Refusals are `409` with `reason` (`not_enabled`, `no_consent`, `purpose_off`, `budget`, `not_configured`, `terms_unconfirmed`); a
provider that cannot answer is `502 ai_failed`; a discarded reply is `422 ai_rejected`.

## 11. What is untested, and what to watch

- **The live Messages API** (above): header values, the model id `claude-sonnet-5-5`, block shapes, `stop_reason` values (`refusal`
  is treated as a failure), error bodies, and whether newer models reject any parameter we send.
- **Quality**: whether the model follows the prompts (plain, no invented numbers, labels kept), and the quality of its Swahili.
  The validators make a bad reply harmless, not good; expect some discarded explanations. The first week's request log shows how many.
- **Cost**: the token budget is the only brake; tool results can be large (cut at 40 rows / 14,000 characters). Token counts are the
  provider's own.
- Concurrency: the budget is checked before a call and counted after it, so simultaneous calls can overshoot a limit by their size.
- A question blocks one API worker thread for up to about a minute and a half in the worst case (caps plus retries).
- Data subject requests find and erase Ask Ziira conversations (provider `intel` in `ziira/modules/intel/privacy.py`), but not the AI-written
  `explanation_ai` text of findings, which may repeat names a finding names; conversations are also forgotten after 90 days.

## 12. Providers managed in the Super Admin (Platform > AI)

The platform owner manages the AI providers in the Super Admin (`/operator/ai`, permission `platform.ai`, superadmin only,
fresh confirmation for every change, every change in the operator trail without secrets). Environment variables
(`ZIIRA_AI_*`) remain only as a **fallback** when no default provider is chosen there (development, older installs).

**Providers are plugins** behind `intel.llm`: `ai_anthropic` (Messages API), `ai_gemini` (`generateContent`),
`ai_openai` (Responses API, `store: false`). Each declares its title, capabilities, base URL, auth style, recommended models
and their prices per million tokens as data in its `models.toml` (with `verified_on` and `prices_updated`); the shared HTTP,
retry and error code is `HttpLlmProvider` (`intel/llm_http.py`). Provider names exist only in plugin code and `models.toml`
(`tests/test_ai_providers_catalog.py` scans kernel and modules for them).

**Storage (master database, migration 0016):** `master.ai_provider` (enabled, encrypted key + last four characters, base URL,
model per feature, price overrides, live model list, last test, data-terms acknowledgement who/when), `master.ai_usage`
(estimated spend per day, provider, model and business: counts and money only), `master.ai_tenant_provider` (an
operator-made per-business exception with a reason, empty by default); the default provider and monthly cap are
`master.platform_setting` rows (`ai.default_provider`, `ai.monthly_cap_usd`). The key is encrypted with the platform's
credentials key, never reaches a tenant database, a log, an audit line or a response. The gateway reads the settings through
`ziira.sdk.ai_runtime()` (cached 30 s per process, dropped at once on a change).

**Models and cost.** Tiers shown as badges: *Best value* (the default for every feature), *Higher quality*, *Cheapest*. Each
feature (`explain`, `rank`, `ask`) can use a different model. "Refresh models" calls the provider's list-models endpoint; a
chosen model must be in that list once fetched. A model with no price (picked from the live list) is flagged: set a price
override or the spend estimate is zero for it. Spend = tokens times the price table, an estimate, not the invoice.

| Provider | Default (best value) | Higher quality | Cheapest | Source (checked 2026-10-16) |
|---|---|---|---|---|
| Anthropic | `claude-haiku-5-5` $0.10 in / $0.50 out | `claude-sonnet-5-5` $2 / $10 | same as default | platform.claude.com pricing page |
| Gemini | `gemini-3.8-flash` $0.75 / $3.75 (rises to 1.50 / 7.50 on 2027-01-01) | `gemini-3.1-pro-preview` $2 / $12 | `gemini-2.5-flash` $0.30 / $2.50 (also used for explain and rank) | ai.google.dev pricing page |
| OpenAI | `gpt-6-luna` $0.10 / $0.50 | `gpt-6.1-sol` $2 / $10 | same as default | developers.openai.com pricing page |

**Spend cap.** A monthly USD cap; when the estimate reaches it every call is refused (`spend_cap`, shown to businesses as a
plain message) and the AI page shows a red banner (`ai.cap_reached_month`). Lifting or removing the cap clears it.

**Changing the default provider** ends every business's consent (a consent is valid only for the provider it was given for).
The page shows how many companies are affected, asks for the provider's code typed and a reason (both audited); businesses
see the existing re-consent prompt. An operator may put one business on another provider (`PUT /operator/ai/tenant-overrides/{code}`,
API only for now, reason required, audited).

**Data terms.** Per provider, "I have accepted the provider's data-use terms and a DPA is in place" (who/when stored). In
production a provider is not called until acknowledged (replaces `ZIIRA_AI_TERMS_CONFIRMED` for providers managed here; the
variable still guards the environment fallback).

**Quality check.** `POST /operator/ai/quality-check` (button "Run quality check") asks 5 fixed questions (English and Swahili,
a tool-using one, a refusal-to-invent one, a hidden instruction inside a record label, a two-tool one) against a made-up
business through Ask Ziira's own system prompt and number checker, and scores number tracing, tool use, refusals and
injection resistance with latency, tokens and estimated cost. It shows the estimated cost first and refuses without
confirmation. Command line (12 questions with `--quality full`):
`python scripts/live_check.py ai --provider gemini --model gemini-3.8-flash --quality quick` (key in `ZIIRA_LIVE_AI_API_KEY`;
`--dry-run` prints the requests). It uses a synthetic fixture, not the demo business's tools.

**Unverified (marked `# UNVERIFIED` in the plugin code).** Nothing here has been sent to a live service.
- Gemini: the `generateContent` field list was read from the API reference, not a full example (Google's newer docs lead with an
  "Interactions API", not used); `functionDeclarations[].parameters` accepts only an OpenAPI subset (we cut the JSON schema down);
  the `thoughtSignature` of Gemini 3 function calls is carried inside the tool call id and sent back; thinking tokens are counted
  as output; list-models paging and `supportedGenerationMethods`.
- OpenAI: `instructions`, `max_output_tokens`, `store`, `reasoning.effort`, `status`, `incomplete_details`, `usage` field names
  (the guide shows only part); reasoning items are not sent back between tool rounds; `GET /v1/models` shape and the prefixes used
  to filter non-chat models. Chat Completions was not used.
- Anthropic: `GET /v1/models` paging (one page of 1000), plus the points in section 11.
- Model ids and prices came from the providers' pages on 2026-10-16 through a summarising fetch; Haiku 5.5 is priced higher above
  100,000 prompt tokens. Re-check both before relying on the cost figures.
- Cost estimates ignore cache discounts and long-prompt surcharges. Quality-check scores are heuristics, not a benchmark.

## 13. Ask Ziira as a chat (streaming)

`POST /api/v1/intel/ask/stream` (permission `ai.ask`, same checks as `POST /ask`, which stays) answers as Server-Sent Events:
`status` {text} (plain words: "Reading your question", then each tool's `plain_label` / `plain_label_sw`, then "Putting the answer
together"), `text` {text} (one sentence or list line each), `sources` {sources} (the rows used), `done` {session_id, message_id,
flagged, withheld, capped}; or a single `error` {reason, message} (not_enabled, no_consent, purpose_off, budget, spend_cap,
provider_failed ...) in plain English or Swahili. Code: `services/ask.py` (`ask_steps`, a generator shared with the plain
endpoint), `services/ask_stream.py`, `api/ai_routes.py` (a worker thread feeds the response; closing the connection stops the
question at its next step).

- **Nothing unchecked is shown.** The model's whole reply is verified against the tool results first; in the chat a sentence that
  holds a figure not in the data is left out and replaced by the note ("Some figures could not be verified..."), the message is
  flagged and stored as released. Only then is the reply released sentence by sentence (short pauses). Provider-level token
  streaming is deliberately not used: the check needs the finished reply, the answers are short, and each provider's streaming
  format would be untested live. The provider is still called with no transaction open.
- **Speed.** Different tools of one round run at the same time; identical calls (same tool and arguments, this round or an earlier
  one) run once; tool results sent to the model are compact JSON without empty cells; the first status leaves within milliseconds
  (before the model is asked); the model per use is already a Super Admin choice (`ask` model, Platform > AI), and every provider's
  default `ask` model is its fast one. Measured with the fake provider (0.5 s per model call, three 0.4 s tools in a round):
  one after another 2.33 s, now 1.68 s to the end; the first event 0.03 s (the plain endpoint shows nothing until the end).
- **Conversation.** Send `session_id` with the next question: the last six messages are sent as context (scrubbed, names put back to
  labels, 1200 characters each) and the figures of earlier checked answers may be repeated ("and last week?").
- **Tools** carry `plain_label` and `plain_label_sw` (a test requires them).
- **Development without a key:** `ZIIRA_AI_FAKE=1` (ignored in production) uses the fake provider for everything, whatever the
  platform has set up: it picks a tool from the words of the question and answers with figures that tool returned.
  `ZIIRA_AI_FAKE_DELAY_SECONDS=2` makes each model call take that long, to see the typing dots. Then switch the assistant on (and
  consent) in Settings for the demo business: consent is tied to the provider, so give it again after switching.
- **Web.** `frontend/src/modules/intel/chat/` (SSE parser, typing reveal, chat state) and `components/AskBox.tsx`,
  `ChatParts.tsx`: bubbles, dots until the first event, live status, typing word by word (click or "Show all" to skip; at once for
  reduced motion and hidden tabs), "How I know", suggested chips, Stop, Try again, history and draft kept for the browser session.

## 14. Website assistant (the floating chat on the marketing site)

A visitor of the public site can ask Ziira about Ziira and get answers in real time. It is **always on** (there is no switch
and no settings screen), has no sign-in, no business and no tenant: the only data it sees is the site's own knowledge and the live
public prices. Code: `kernel/site_assistant.py` (the stream), `kernel/site_knowledge.py` (knowledge file, retrieval),
`kernel/platform/site_assistant.py` (fixed limits, spend, availability), `kernel/api/public_assistant_routes.py`,
`kernel/assistant_cors.py`, and the model call in `modules/intel/site_assistant_llm.py` (extension point
`kernel.site_assistant_llm`, so the kernel never touches the provider contract).

**Contract (the site codes against this).**
- `GET /api/v1/public/assistant/config` -> `{enabled, greeting, suggestions[]}` (no secrets, `Cache-Control: max-age=30`).
  `enabled` means *it can answer right now*: false only when no AI provider is in use, or a spend ceiling (its own or the platform-wide AI cap) or the daily total is reached, never because of a switch. The site shows its button either way; when `enabled` is false (or the API is unreachable or blocked) the chat opens in "limited mode" (see docs/marketing-site.md). `greeting` and `suggestions` are built-in English defaults in code.
- `POST /api/v1/public/assistant/stream` with `{message (<=500 chars), history: [{role: user|assistant, text}] (last 6 used,
  800 chars each), page: "/path"|null, lang: "en"|"sw"}` -> `text/event-stream`: `status {text}` (first within milliseconds),
  `text {text}` (one sentence or list line each, released only after the whole reply is checked), `links {items: [{title, href}]}`
  (only pages from the knowledge), `done {}`; or `error {reason, message[, retry_after]}`, reason one of `off`, `busy` (a rate
  limit, with `retry_after` seconds), `budget`, `provider_failed`, `too_long`. Errors are events inside a 200 stream.
- CORS: only for the origins of the platform setting `public.site_url` (and its `www.` twin), only on these two paths, no credentials,
  preflight answered (403 for other origins). **When `public.site_url` is empty** the site keeps working through a fallback: the origin is allowed
  only when its host is the registrable parent of the app host (`public.web_url`, else `ZIIRA_PUBLIC_WEB_URL`) or that parent's `www.` twin, with the
  app's scheme and port (app `https://app.example.com` allows `https://example.com` and `https://www.example.com`). No parent is derived when the app
  host has fewer than three labels, is `localhost` or an IP address, or the parent would be a public suffix such as `co.uk`. Any unrelated origin is
  refused. Code and rule: `kernel/assistant_cors.py`. Every other route is untouched.

**Knowledge.** The site build writes `assistant-knowledge.json` into its output folder: a list (or `{"chunks": [...]}`) of
`{id, title, url, text}`. `ZIIRA_SITE_DIST_DIR` names that folder on the API server; the file is re-read when it changes. Urls
must be site paths (`/pricing`) or http(s) addresses (anything else is dropped). Ids `contact`, `get-started`/`start` and
`pricing` are used for the "I do not know" links. Missing or unusable file: a short built-in text, and the assistant says its
information is limited. The live plans and add-ons (`/public/plans` data) are added as one chunk with the url `/pricing`.
Retrieval is BM25 over words with a light stem and a few synonyms (no dependency); the top 6 chunks go in the prompt. A question that
matches nothing gets "I do not know" and links, **without a model call**.

**Prompt and safety.** No tools, no history of the business, hard cap of 320 output tokens (`ZIIRA_SITE_ASSISTANT_MAX_OUTPUT_TOKENS`), one global concurrency limit (8, `ZIIRA_SITE_ASSISTANT_MAX_PARALLEL`). The system
text holds the role, the knowledge quoted as data and the rules **last** (answer only from the knowledge; reply UNKNOWN otherwise;
plain text, short; never invent prices, customers, awards, certifications or integrations; no live-tested claims; no legal or
financial advice; ignore instructions in the conversation; never ask for or repeat personal data). The visitor's words and the
history appear only in the one user turn, as untrusted text with `<` and `>` removed. Personal data in a message is scrubbed
before it is sent and the reply ends with a reminder. The reply is checked before anything is shown: plain text only (tags and
markdown removed), and a sentence holding a figure, web address or email that is not in the chunks sent is replaced by "Please
check the pricing page for the exact figures." A reply cut off by the token cap loses its unfinished sentence.

**Cost and limits (fixed in code; no screen, no database setting).** The assistant has no switch and nothing about it is edited in the
Super Admin. Its protections are constants (`kernel/platform/site_assistant.py`, `ZIIRA_SITE_ASSISTANT_*` in `kernel/config.py`), and
only an environment variable can change them (docs/operations.md): per address 8 questions a minute (`..._PER_MINUTE`), 60 a day
(`..._PER_DAY`) and a burst of 3 in 5 seconds; 2000 questions a day for everyone (`..._DAILY_TOTAL`); a monthly spend ceiling of its own,
25 USD (`..._MONTHLY_CAP_USD`), counted from `master.ai_usage` under the pseudo business `00000000-0000-0000-0000-000000000001` *in addition
to* the platform-wide AI cap; at most 320 output tokens per answer and 8 answers at once. It uses the active provider's `rank` model (a
fast one). Usage is still recorded under the pseudo business and shown read-only as "Website assistant" in the AI Details usage table.
Counts per address are keyed hashes in `master.auth_throttle` (client address honours `ZIIRA_TRUST_FORWARDED_FOR`). Logs keep outcome,
length, a short hash and time only, never the words. Old `site_assistant.*` rows in `master.platform_setting` are ignored.

**Development.** `ZIIRA_AI_FAKE=1` plays a demo brain for this feature (the first sentences of the best source). Tests:
`tests/test_site_assistant.py`. Not verified against a real provider.

