# The AI layer: explanations, ranking and Ask Ziira

The AI layer of Ziira Intelligence (`ziira/modules/intel`, spec section 16). A language model writes **sentences**; it never
supplies **figures**. Every number a person sees comes from a check or a query over the business's own records, and a reply
whose numbers cannot be traced back to those records is discarded or marked.

> **Not run against the real service.** The Anthropic request and response shapes (`ziira/plugins/ai_anthropic/provider.py`)
> were written from Anthropic's public documentation. Everything is tested against a scripted fake provider and a pretend
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
