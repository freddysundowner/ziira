# Pilot playbook

How to take the first businesses live. Spec: `docs/specs/Ziira_Intelligence_1.0.txt` ("Trust, limits and rollout") asks for a **30-day pilot with 5 to 6
businesses** and defines success as *most pilot businesses pay to continue, and Ziira identifies problems they were not aware of*. This
playbook turns that into steps. Read `docs/go-live-checklist.md` first: it lists what must be true before anyone's real data goes in.

## Who to pick

Businesses where staff handle money or stock without the owner watching: multi-branch retail, distribution, absent-owner outlets, cash-heavy shops.
Mix: some with an existing system or spreadsheets (they import), some with none. Avoid, for the first pilot: businesses that need tax-authority
submission (eTIMS is parked), payroll with unusual statutory rules you cannot verify, or more than ~5 branches.
For each, agree in writing: what data goes in, who the contact is, that findings are questions and not accusations, and the 30-day review date.

## Before day 1 (one hour, you)

1. The business registers itself (`/register`) or you create it: `ziira create-tenant ... --currency XXX --timezone Area/City` (all business modules
   are on by default). Confirm the owner signs in.
2. Settings: company **timezone**, phone calling code, tax number (as the business writes it), receipt/invoice footers, negative-stock policy.
3. Security: the owner sets up the second factor and saves the backup codes; choose the second-factor policy (`privileged` recommended).
4. Channels: set up SMS/email for the business (Settings -> Notifications) and send one test message (`docs/live-checks.md`). Leave Intelligence alerts
   **off** (`intel_alert_channel = off`) for the first two weeks: findings and briefs appear in the app only.
5. `ziira verify <tenant>` is clean; a backup exists (`ziira backup --tenant CODE --dir ...`).

## Days 1 to 5: connect and map

- Branches, tills (Devices), stores (Locations), staff and roles (Users: give each person the narrowest role and scope: cashiers at one branch, a branch manager per branch,
  finance on the company). Each person with a powerful role sets up the second factor.
- Catalogue: units, tax codes and rates **as the business's own documents say**, price list, products (`docs/data-import.md`: import from CSV, check the reconciliation
  report against their file, keep the rejected-rows file for follow-up). Opening stock by location. Customers and suppliers. Chart of accounts (import or the starter chart).
- Rehearse with the owner: open a till, sell, hold, void with a reason, close the till, receive stock, enter a supplier bill, pay it, run a report. Fix anything that confuses them *that day*.
- Payroll (if used): the owner defines the business's statutory rules from the official notices, a second person verifies them, an accountant checks a few payslips independently before a real run.

## Weeks 1 to 2: first briefs

- Turn on briefs for the owner and managers (Command Center -> My briefs): daily by app first, then email/SMS once the channel is proven.
- Run the **look-back**: `ziira run-task <tenant> intel.refresh_baselines` then `intel.run_checks` after importing past months; sit with the owner and walk through what Ziira
  would have caught (the spec's week-2 session). Tune noisy checks (Findings -> Check settings): loosen limits, switch off what does not apply.
- Daily for the pilot team (you): Command Center health (`/readyz`, `/metrics`), failed notifications, the exceptions inbox, `ziira verify`.

## Weeks 3 to 4: alerts and managers

- Turn alerts on (`intel_alert_channel` = email or sms, `intel_alert_min_severity` = high) once the owner agrees the findings are worth a message; add the branch managers.
- Ask managers to **explain** findings in the app (the answers are recorded: they protect honest staff). Raise `intel_action_level` to 2 only if the owner wants to ask people directly.
- Weekly review call: findings raised, how many were real, how many were noise, what the business did about them, what they asked for that is missing.

## What to measure

| Measure | Where | Good |
|---|---|---|
| Problems the owner did not know about | findings marked explained/resolved with a real cause | at least one per business |
| Noise | findings dismissed as "not a problem" / total | under 30% after tuning |
| Daily use | sign-ins, tills opened, briefs read | owner reads the brief most days |
| Data quality | `ziira verify`, reconciliation of imports, till variances | clean; variances explained |
| Reliability | `/metrics`: failed jobs, notification failures; support requests | none stuck, near-zero failures |
| Willingness to pay | the 30-day conversation | most say yes |

## Support during the pilot

Use support access (Settings -> Support access): the business grants read-only or full access for a limited time with a reason; everything staff do is logged
and visible to the owner. Do not ask for passwords. Keep a log of every issue (symptom, cause, fix, how long) in the issue tracker: it becomes the backlog.

## Exit

After 30 days: export their data if they leave (`docs/privacy.md`), run `ziira backup`, write down per business: the findings that mattered, what to fix, the decision to continue.
Decide as a team whether the criteria were met before opening to more businesses.
