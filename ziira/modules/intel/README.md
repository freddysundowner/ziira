# Ziira Intelligence

**Status:** built (phase 10). See `docs/intelligence.md`.

| | |
|---|---|
| Schema | `intel` (migrations `0001_init`, `0002_findings`) |
| Requires | kernel only (reads no other unit: units supply checks and baseline metrics through `intel.check` and `intel.baseline_metric`) |
| Publishes | `finding.created`, `finding.asked` |
| Recurring | `intel.run_checks` (6 hourly), `intel.refresh_baselines` (weekly) |
| Permissions | `findings.view`, `findings.manage`, `findings.respond` |

## Layout

```
public.py        the contract for checks (`IntelCheck`, `Candidate`, `Record`) and baseline metrics (`BaselineMetric`), and reads of findings
domain/          model (candidates, baselines), rules (severity, life of a finding, ranking, unusual), messages
services/        engine (run checks, keep findings in step), findings (what people do), alerts, baselines, checks_admin
repository/      SQL for the intel schema
kernel_checks.py Intelligence's own checks over approvals, role grants, the audit log and the exceptions inbox
api/             findings, checks (tune), run now; ai_routes.py: the AI assistant (status, settings, call log, Ask Ziira)
jobs.py          the recurring runs (and the AI background tasks)
ask_tools.py     Intelligence's own ask tools; every unit has its own `ask_tools.py`
fake_llm.py      the scripted AI provider for tests and development
privacy.py       Ask Ziira conversations for data subject requests
```

The optional **AI layer** (explanations, ranking, Ask Ziira; off until an Owner consents) is in `services/ai.py` (the one gateway),
`ai_admin.py`, `explain.py`, `ask.py` and `domain/ai_rules.py`, `llm.py`, `scope.py`. See `docs/ai.md`.
