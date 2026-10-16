# Intelligence and the Command Center

Ziira Intelligence checks the business every day and says what needs attention; the Command Center shows the figures and
sends the briefs. Both are built into Core (the "inside Ziira Core" mode of `docs/specs/Ziira_Intelligence_1.0.txt`).
Standalone mode (Intelligence on a business's existing system) is the `connect` unit: `docs/standalone-mode.md`.

```
units (pos, inventory, ...)                  intel                              command
  IntelCheck  ──── intel.check ───────▶  engine ──▶ findings ──▶ alerts          PulseSource ◀── command.pulse_source ── units
  BaselineMetric ─ intel.baseline_metric ▶ baselines          ▲                      │
                                                              └── top findings ──▶ briefs  ◀── pulse figures (stored per day)
```

Nothing in `intel` or `command` reads another unit's tables. **Units supply checks and figures through extension
points** (`docs/extending-units.md`), so each check lives next to the data it reads, is tested with that unit, and a plugin
can add more. Only units enabled for the business take part.

## The checks engine (`ziira/modules/intel`)

- `ziira worker` runs `intel.run_checks` for every company every 6 hours (and `ziira run-task <tenant> intel.run_checks` runs it
  now; the "Run checks now" button calls `POST /api/v1/intel/run`). Each check runs in a savepoint: **a failing check never stops
  the others** and is put in the exceptions inbox.
- A check returns *candidates*. The engine turns each into a **finding** identified by `(check code, fingerprint)`:
  the same problem seen again is the same finding (updated, not duplicated); a *state* check (`auto_resolves = True`) closes a
  finding it stops reporting; an *event* check keeps it until a person deals with it; a resolved finding that comes back is
  reopened; a dismissed one is not raised again. Every step is an event on the finding (who, when, note).
- Findings have severity (info, low, medium, high, critical), `amount` (money at stake, used for ranking), a plain-language
  `summary`, a `recommended_action`, and **evidence**: the records behind it and the figures. Numbers come from records,
  never from a guess. Flags are questions, not accusations.
- **Who sees what**: findings are scoped like everything else: a finding with a `branch_id` is seen by people whose role
  (`findings.view`) covers that branch; a company-level finding by company-wide roles. Roles: Finance Manager `view` + `manage`,
  Accountant `view`, Branch Manager `view` + `respond` (can explain what is assigned to them), Owner all.
- **What people do**: acknowledge, explain (the answer is recorded with who gave it), resolve, dismiss (a reason is required),
  assign, and *ask someone to explain* (level 2, below).
- **Tuning**: a business switches a check off or changes its limits (`PATCH /intel/checks/{code}`); limits are the check's
  `params` with their defaults.
- **Baselines**: units supply observations (`BaselineMetric`); `intel.refresh_baselines` weekly stores mean, standard deviation and
  95th percentile per metric and dimension from the last 90 days. A check calls `ctx.baseline(metric, key)` and `is_unusual(...)`
  (more than 3 standard deviations over the mean **and** above the 95th percentile, with at least 14 observations).
- **Alerts**: with the company setting `intel_alert_channel` (`off` by default, `sms` or `email`), new findings at or above
  `intel_alert_min_severity` (default `high`) are queued to the people whose role covers them (`kernel.notification`, so opt-outs and
  retries apply). Anything below waits for the brief. The finding becomes `sent`. `intel_alert_channel` may be any channel the business has (`sms`, `email`, or a chat channel from a plugin)
  (then SMS and email are the fallbacks); each person may choose their own channel for alerts and quiet hours in My account >
  Notifications (`docs/channels.md`), and a critical alert passes quiet hours only if they allowed it.
- **Levels of action** (company setting `intel_action_level`; every business starts at 1, and moving up is its choice): 1 reports
  only; 2 also lets a manager ask a named person to explain a finding; **3 prepares** suggested actions for a person to approve;
  **4 acts within limits** (routine actions under the owner's rules). Raising it to 3 or 4 needs the Owner (permission
  `intel.automation`); lowering needs only `settings.manage`. Details in "Actions: levels 3 and 4" below.
- Intelligence's own checks (`controls.*`, `ziira/modules/intel/kernel_checks.py`) read what the platform records: an approval decided
  by its requester, someone given wide access, a burst of activity outside working hours (read in the company's time zone), and
  exceptions nobody has reviewed.
- **AI** (`docs/ai.md`): an optional layer, **off until an Owner consents**. A model (provider behind the `intel.llm` extension point;
  Anthropic's Messages API in the `ai_anthropic` plugin, request shapes not yet run against the live service) writes plain-language
  **explanations** of findings (`explanation_ai`, labelled AI-written, kept only if every number in it is in the finding's own facts),
  **orders** the top findings (kept only if it is exactly a permutation; otherwise `domain/rules.py: rank_score` decides), and answers
  **Ask Ziira** questions by calling **tools** that units offer over their own data (`intel.ask_tool`) as the person asking, within
  their branches. Figures still come only from checks and queries; the deterministic text is always there and always the fallback.

### Writing a check

```python
# ziira/modules/<unit>/hooks.py (or imported from it)
from ziira.modules.intel.public import INTEL_CHECK, Candidate, CheckContext, IntelCheck, Record, fingerprint
from ziira.sdk import provides

@provides(INTEL_CHECK)
class StockOut(IntelCheck):
    code = "inventory.stockout"            # "<unit>.<name>", unique
    title = "Out of stock"
    area = "stock"                          # cash_sales customers suppliers stock cash_planning books people controls
    description = "A product has run out at a branch."
    default_severity = "medium"
    params = {"days": 30}                   # the business may change these
    auto_resolves = True                    # a state: closes itself when it clears

    def run(self, session, ctx: CheckContext) -> list[Candidate]:
        ...                                 # read with SQL on your own tables; never write
        return [Candidate(fingerprint=fingerprint(self.code, product_id, branch_id), severity="medium",
                          summary="Cement is out of stock at Thika.", recommended_action="Reorder it.",
                          company_id=ctx.company_id, branch_id=branch_id, amount=value_at_risk,
                          records=(Record("products.product", product_id, "Cement 50kg"),))]
```

In the unit's `manifest.toml`: `optional = [..., "intel"]` and `[extends] implements = ["intel.check"]`. Test it end to end with the
real engine (`engine.run_company`) as `tests/test_intel.py` does. Keep summaries plain and give every check a limit a business
can change; false alarms train people to ignore the system.

## Actions: levels 3 and 4

Rules that hold everywhere (they are tested): nothing involving money, prices, credit or stock changes without a person unless
the owner has set a rule **and** the action is one that moves no money; **Ziira never moves money**; every action is recorded (the
action log, the finding's history and the audit log); an action is done through the owning unit's normal services, **as the person who
approved it**, so that unit's permissions and approval rules apply to them.

```
finding ──▶ providers propose ──▶ suggestion (waiting) ──▶ a person approves (optionally edits) ──▶ executed as them ──▶ log
                                        └─▶ level 4 + provider auto_allowed + owner's rule covers it + daily cap left
                                            ──▶ executed as "Intelligence" (channel `intelligence`, ONE permission) ──▶ log
```

- **Proposing** (`services/actions.py`, called by the checks engine at the end of each company run): at level 3 or 4 each open finding
  that no provider has looked at yet (new, or come back after being resolved) is offered to the providers whose `check_codes` match.
  A suggestion is unique per finding + action + parameters; a turned-down or failed one is not made again; a done one is not repeated
  for 7 days; a run looks at no more than 100 findings and adds no more than 100 suggestions per company. When the finding closes
  (by itself or by a person) its waiting suggestions expire. Lowering the level below 3 withdraws what was waiting (and approving is
  refused meanwhile). A provider that raises an error is put in the exceptions inbox and skipped.
- **Approving** (`POST /api/v1/intel/actions/{id}/approve`): needs the provider's `needs_permission` for the finding's company and branch
  (a branch manager cannot approve another branch's). Parameters may be edited if the provider's schema marks them editable; they are
  validated again, and the provider checks them against the world again at execution. Success and failure are both recorded (a failure
  is shown, changes nothing, and may be tried again by a person). Approving twice does nothing the second time. `reject` needs a reason.
- **Rules** (`/intel/automation/rules`): **creating, editing, resuming or switching on a rule needs `intel.automation` (Owner)** because the
  rule is the owner's decision; with `findings.manage` a person can list the rules and pause or switch one off (doing less is always allowed). per action type, conditions from a safe vocabulary (every
  provider: `branch_id`, `max_amount`; plus its own `rule_schema`), a daily limit (counted in the company's time zone), pause/resume.
  A rule only works at level 4, only for a provider with `auto_allowed = True` whose `needs_permission` is not a money permission
  (`domain/action_rules.py: MONEY_PERMISSIONS`); the engine re-checks this at run time, so a rule written straight into the database for a
  draft, a price or a credit limit is ignored. An automatic action that fails is recorded, put in the exceptions inbox and **never retried
  by itself**.
- **What the providers do today** (each in its unit's `action_providers.py`):

| Action | For findings of | Needs | Automatic? | What it does |
|---|---|---|---|---|
| `purchasing.draft_purchase_request` | `inventory.out_of_stock`, `low_stock` | `po.create` | no | A draft request for the branch: the larger of the gap to the reorder level and the last 30 days' sales; the usual suppliers (most receipts, then most recent) go in the line's note |
| `purchasing.propose_price_update` | `purchasing.margin_squeeze`, `supplier_price_rise` | `prices.manage` | no | A new tax-inclusive price on the default list from tomorrow that gives the new cost the margin the old cost had (`purchasing/domain/repricing.py`); through Products' price service |
| `pos.send_payment_reminder` | `pos.customer_overdue` | `receivables.manage` | **yes** | The business's usual reminder (the company's `reminder_channel`; opt-outs respected) for the customer's oldest overdue invoices (3 at most); rule conditions `min_days_overdue`, `channel` |
| `pos.hold_credit` | `pos.customer_overdue`, `pos.credit_to_overdue_customer` | `customers.manage` | no | Lowers the credit limit to what the customer owes, through CRM's credit-change flow |
| `people.nudge_approver` | `people.leave_waiting`, `people.payroll_overdue` | `findings.manage` | **yes** | A message to whoever holds `leave.approve` (or `payroll.approve`/`payroll.pay`) for the branch, by the alert channel |
| `finance.ask_for_reconciliation` | `finance.stale_reconciliation` | `findings.manage` | **yes** | A message to those holding `bank.reconcile` |
| `intel.nudge_exceptions_reviewers` | `controls.exceptions_backlog` | `findings.manage` | **yes** | A message to those holding `exceptions.manage` |

  The nudges need `intel_alert_channel` set and a person who can be reached (a phone, an email or a verified number on a chat channel);
  otherwise nothing is proposed. Automatic messages respect each person's **quiet hours**: they are deferred to the end of the
  quiet period, never dropped. `pos.send_payment_reminder` can send by any channel the business has (on a chat channel a template with the customer, amount in the
  company currency, due date and business; SMS/email as fallbacks).
- **Adding a provider** (in the unit that owns the effect; "intel" under `optional` and `"intel.action"` under `[extends] implements`
  in the manifest):

```python
# ziira/modules/<unit>/action_providers.py, registered in hooks.py with provides(INTEL_ACTION)(MyAction)
from ziira.modules.intel.public import ActionContext, ActionProvider, ActionResult, FindingInfo, Proposal

class MyAction(ActionProvider):
    type = "<unit>.<name>"                      # unique
    title = "Plain title"; description = "What it does, in a sentence"
    check_codes = ("<unit>.<check>",)           # the findings it can act on
    needs_permission = "<unit>.<permission>"    # held by the approver, with scope for the finding's company/branch
    auto_allowed = False                        # True ONLY for routine, reversible, non-monetary actions
    params_schema = {"properties": {"quantity": {"type": "number", "title": "Quantity", "minimum": "0.0001"}},
                     "required": ["quantity"]}  # string/integer/number/boolean/uuid/date; editable: False fixes a value
    rule_schema = {}                            # the conditions an owner's rule may set (auto_allowed only)

    def proposes(self, session, finding: FindingInfo) -> list[Proposal]: ...      # read only; [] when nothing sensible
    def execute(self, session, context: ActionContext, params) -> ActionResult: ...   # services of your own unit or others' public.py
```

  Rules for providers: `proposes` reads and never writes; `execute` calls the owning unit's service functions (never SQL into
  another unit's tables), re-checks its parameters and the facts (the world may have changed), is safe to run twice, returns what it
  created as `created_refs` for the screen to link to, and returns `ActionResult(False, message)` rather than half-doing it. An
  automatic provider's class must not mention the books, payments, stock movements, prices or credit limits
  (`FORBIDDEN_FOR_AUTO`; `tests/test_intel_actions.py` scans every registered one). Test it end to end with the real engine as
  `tests/test_intel_action_providers.py` does.
- **Reply to act**: when a suggestion is made, the people who can decide are messaged on their `approvals` channel; on a channel that declares reply buttons
  (`supports_buttons`, e.g. WhatsApp with the Lead Intel plugin) the message has **Approve / Reject / Why?** buttons. Intelligence
  knows no channel by name: it asks the channel layer for "the person's preferred available channel" and for a capability. A reply from a verified number is run as that person through the same
  `actions.approve` / `reject` (so permissions and approval rules apply; the action log, the finding history and the audit log record
  the channel `chat`), free text goes to Ask Ziira, and a number that is not exactly one active user's verified number is
  ignored without a reply. `ziira/modules/intel/inbound.py`, `services/approver_messages.py`, `services/channel_questions.py`; the
  channel layer is `docs/channels.md`.
- **Screens**: the finding page has a "Suggested actions" card; **Findings > Actions** is the inbox of suggestions waiting for the
  signed-in person plus the history; **Settings > Intelligence actions** has the level, the rules and the action log.
- **Not built**: approving by SMS or email reply; approving Core's own approval requests (leave, payroll) by reply; rule conditions
  on the customer's group or the size of one invoice (only the finding's branch and amount). Chat channels need a plugin that provides one
  (`leadsintel`) and have not been run against a live service. With no such plugin on, suggestions are announced nowhere and wait in
  the app; alerts and briefs go by SMS or email; nothing breaks.

## The Command Center (`ziira/modules/command`)

- **Pulse figures**: units supply numbers for a day through `command.pulse_source` (`PulseSource.figures(session, company_id, day)`
  returning `Figure(metric, label, kind, value, branch_id, higher_is_better)`). `command.refresh_pulse` stores them hourly in
  `command.pulse_figure`; screens and briefs read the stored copy, never raw tables at page load (the first look of a day collects
  once). Company-wide and per-branch figures are both stored; each person sees those their `command.view` role covers.
- **Overview** (`GET /command/overview`): today's figures so far against yesterday, plus the open findings in the person's scope.
- **Briefs**: a person chooses a daily and/or weekly brief (time in the **company's time zone**, channel `in_app`, `email` or
  `sms`). `command.send_briefs` (every 10 minutes) sends those whose time has passed and have not been sent today (a brief missed
  while the worker was down still goes out later the same day). A brief says what happened (figures against the period before) and
  what needs attention (top findings within the person's role), in plain words; SMS carries the short form. A missing contact falls back
  to the app. Briefs are stored so they can be read again.
- A brief may go by any channel the business has (the short form on chat channels; the `daily_brief` template when the window is closed) as well as in-app, email
  or SMS, and follows the person's own choice and quiet hours (`docs/channels.md`).

## Settings (per company, `PATCH /companies/{id}/settings`)

| Setting | Default | Meaning |
|---|---|---|
| `timezone` | `UTC` | The company's time zone (IANA name): briefs and "odd hours" are read in it. **Set it for every business.** |
| `intel_alert_channel` | `off` | `off`, or a channel the business has (`sms`, `email`, a chat channel): where urgent findings are sent. If the channel is switched off later the value is kept and alerts go by the next channel |
| `intel_alert_min_severity` | `high` | Findings at or above this are sent as alerts |
| `intel_action_level` | `1` | `2` lets managers ask people to explain a finding; `3` prepares suggested actions for approval; `4` also runs the owner's automation rules. Raising it to 3 or 4 needs `intel.automation` (Owner) |
| `ai_enabled`, `ai_explanations`, `ai_auto_explain`, `ai_ask`, `ai_monthly_token_limit` | off, on, off, on, 2,000,000 | The AI assistant (changed on **Settings > AI assistant**, which records the consent); see `docs/ai.md` |

## Standalone checks

The `connect` unit supplies `standalone.<name>` checks, baselines and pulse figures that read only its own read-only copy of another system's
data (`connect.src_*`). They run only where connections exist and only for the entities a connection supplies; a check whose entity was never
connected stays silent and the Coverage panel says so. A day is judged only once its data is complete. They never look at a Core unit's tables,
so a business using both gets each set about its own data. Where a Core unit now runs the same area at the same branch (judged by
`connect.core_coverage`, which Core units implement) the standalone check stays silent there, unless the business chose to keep both; a paused
connection is not checked. See `docs/standalone-mode.md` ("Core units and standalone checks", "Moving to Core").

**Where a finding comes from.** Every finding says so: `source` is `connected` for a check whose code starts `standalone.` (it read the copy of
the system the business keeps) and `ziira` for any other. It is a computed field on `FindingOut`, on the Command Center's top findings and
filterable with `GET /findings?source=connected|ziira`; the web app shows "From your connected system" / "From Ziira" in the findings list
(with a filter, for businesses that use Connected systems), on the finding page, Home and the Command Center. The page above the findings list
is a slot (`intel.findings.banner`) that Connected systems fills with its "checked twice" banner.

## Extension points Intelligence offers

`intel.check` (a unit's checks), `intel.baseline_metric` (what is normal), `intel.ask_tool` (a question Ask Ziira may put to a unit's
data: `docs/ai.md`, "Adding an ask tool"), `intel.llm` (an AI provider) and `intel.action` (something Intelligence may propose and do).

## Operations

`ziira worker` does everything (checks, baselines, figures, briefs). To try it by hand: `ziira enable <tenant> intel`,
`ziira enable <tenant> command`, then `ziira run-task <tenant> intel.run_checks` and `command.refresh_pulse`; or use the buttons in the
web app. Without a channel set up, nothing is ever sent: findings and briefs appear in the app only.
