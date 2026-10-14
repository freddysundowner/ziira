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
api/             findings, checks (tune), run now
jobs.py          the recurring runs
```
