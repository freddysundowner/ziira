# Intelligence and the Command Center

Ziira Intelligence checks the business every day and says what needs attention; the Command Center shows the figures and
sends the briefs. Both are built into Core (the "inside Ziira Core" mode of `docs/specs/Ziira_Intelligence_1.0.txt`).
Standalone mode on other ERPs is not part of Core 1.0.

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
  retries apply). Anything below waits for the brief. The finding becomes `sent`.
- **Levels of action** (company setting `intel_action_level`): 1 reports only (the default); 2 also lets a manager ask a named
  person to explain a finding (they are messaged and see it as *assigned to me*). Levels 3 (prepare drafts) and 4 (act within limits)
  are **not built**: nothing involving money changes without a person.
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
- WhatsApp is not a channel (decision 2026-10-13); the Intelligence spec's WhatsApp replies are out for now.

## Settings (per company, `PATCH /companies/{id}/settings`)

| Setting | Default | Meaning |
|---|---|---|
| `timezone` | `UTC` | The company's time zone (IANA name): briefs and "odd hours" are read in it. **Set it for every business.** |
| `intel_alert_channel` | `off` | `sms` or `email`: where urgent findings are sent |
| `intel_alert_min_severity` | `high` | Findings at or above this are sent as alerts |
| `intel_action_level` | `1` | `2` lets managers ask people to explain a finding |
| `ai_enabled`, `ai_explanations`, `ai_auto_explain`, `ai_ask`, `ai_monthly_token_limit` | off, on, off, on, 2,000,000 | The AI assistant (changed on **Settings > AI assistant**, which records the consent); see `docs/ai.md` |

## Extension points Intelligence offers

`intel.check` (a unit's checks), `intel.baseline_metric` (what is normal), `intel.ask_tool` (a question Ask Ziira may put to a unit's
data: `docs/ai.md`, "Adding an ask tool") and `intel.llm` (an AI provider).

## Operations

`ziira worker` does everything (checks, baselines, figures, briefs). To try it by hand: `ziira enable <tenant> intel`,
`ziira enable <tenant> command`, then `ziira run-task <tenant> intel.run_checks` and `command.refresh_pulse`; or use the buttons in the
web app. Without a channel set up, nothing is ever sent: findings and briefs appear in the app only.
