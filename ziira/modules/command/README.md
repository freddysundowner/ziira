# Command Center

**Status:** built (phase 10). See `docs/intelligence.md`.

| | |
|---|---|
| Schema | `command` (migrations `0001_init`, `0002_pulse_and_briefs`) |
| Requires | kernel only; optional `intel` (findings in the overview and briefs); units add figures through `command.pulse_source` |
| Recurring | `command.refresh_pulse` (hourly), `command.send_briefs` (every 10 minutes) |
| Permissions | `command.view`, `briefs.manage` |

## Layout

```
public.py        `Figure` and the `PulseSource` contract units implement
domain/          compose (the words of a brief), schedule (when one is due)
services/        pulse (store and summarise figures per scope), briefs (build, deliver, send what is due), overview
repository/      SQL for the command schema
api/             overview, schedules, briefs, dashboard layout
jobs.py          the recurring runs
```
