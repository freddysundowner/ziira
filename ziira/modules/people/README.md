# People, HR and Payroll

**Status:** working for phase 9: employees, pay setup with approvals, shifts and attendance (by hand and from the till),
leave, **statutory rules the business defines itself**, payroll runs (calculate, review, approve by someone else, post to
the books by branch, pay), payslips, a yearly tax card, a return per rule, and a payment file. Nothing about any country
is in the code (see `docs/localisation.md`).

| | |
|---|---|
| Schema | `people` (migrations `0001_init`, `0002_phase9`) |
| Requires | kernel only |
| Optional | finance (payroll posts to the books), payments, pos (till open/close clocks a cashier in and out) |
| Publishes | `employee.pay_changed`, `employee.bank_changed`, `payroll.approved`, `payroll.paid` |
| Subscribes | `till.opened`, `till.closed` |
| API | `/api/v1/people` |
| Permissions | `employees.view`, `employees.manage`, `employee.pay_edit`, `attendance.manage`, `leave.approve`, `payroll.prepare`, `payroll.approve`, `payroll.view`, `payroll.pay`, `payroll.rates` |
| Default roles | HR: employees, attendance, leave, pay edit · Finance Manager: pay edit, prepare, view, pay, rates · Accountant: view, rates · Branch Manager: employees (own branch), attendance, leave · Owner: all |

## Statutory rules: taxes, contributions and levies are the business's data

A business adds the rules that apply to it (`POST /rules`), each with an effective date; a change is a new rule from a
later date, so any past payroll can be reproduced. A rule has a `code`, a `name`, and:

```json
{ "name": "Income tax", "kind": "tax", "order": 30, "base": "taxable", "applies_to": "resident",
  "reduces_taxable": false,
  "employee": {"method": "bands", "credit": "2400",
               "bands": [{"up_to": "24000", "rate": "0.10"}, {"up_to": null, "rate": "0.30"}]},
  "employer": null }
```

* `base`: what it is charged on: `gross` (taxable cash pay), `basic`, or `taxable` (pay after the earlier rules that reduce it)
* `applies_to`: `all`, `resident` or `non_resident` (so a non-resident can have a different rule); an employee can also be
  exempt from named rules (`exempt_rules`)
* `reduces_taxable` and `order`: which deductions lower the pay tax is charged on, and in what sequence
* `employee` / `employer`: a *method* each, or none: `rate` (`rate`, `base_minimum`, `base_maximum`, `minimum`,
  `maximum`), `bands` (progressive, with a fixed `credit` taken off the tax) or `fixed` (`amount`)
* `payable_account_id` (optional, on the rule): the liability account the amount is owed through (otherwise a default)

A rule is saved **unverified**; a different person must *verify* it against the official notice, and a run that used an
unverified rule cannot be submitted. Money and rates are strings, never floats.

## Payroll runs

`POST /payroll-runs` (a period of at most 31 days) -> `calculate` (every payslip, plus the exceptions to review: new joiners,
leavers, pay changes, changed payment details, deductions limited by the pay available, large changes in net pay; *blockers*
are unverified rules, a negative net pay, nobody to pay) -> `submit` -> `approve` (by someone other than the preparer, who
needs `payroll.approve`; the figures are recalculated and must equal the reviewed ones) -> Finance posts it by branch ->
`pay` (Finance moves the net pay out). An approved month is final: attendance and leave inside it cannot change.

* **Pay:** basic from the approved terms in force at the end of the period (prorated by calendar days for joiners and
  leavers), recurring and one-off pay items, overtime from attendance (`overtime_multiplier`, `overtime_hours_per_month`),
  unpaid leave (`payroll_unpaid_day_divisor`), taxable benefits in kind (added to taxable pay, not paid out).
* **Separation of duties:** pay and salary bank details are proposed by one person and approved by another; a rule is
  verified by someone other than its author; a run is approved by someone other than its preparer (also a database check).
* **Posting:** Dr salaries (cash pay) and employer costs, Cr net pay payable, each rule's account (employee and employer
  parts), other deductions payable; the payment: Dr net pay payable, Cr bank / mobile money / cash.
* **Outputs:** `GET /payslips/{id}/print` (data, text, HTML), `GET /employees/{id}/tax-card?year=` (JSON or CSV),
  `GET /payroll-runs/{id}/returns[/{code}]` (what each rule owes, employee by employee, with registration numbers, as CSV),
  `GET /payroll-runs/{id}/payment-file` (full account numbers; audited), `POST /payroll-runs/{id}/send-payslips`
  (email: the payslip; SMS: a short notice). The CSV layouts are generic: adapt them to the form your authority asks for.
* **Not built:** a posted run cannot be reversed (cancel before approval; correct afterwards with the next run or a
  manual journal), paying through a mobile money provider directly (the payment file is for the bank's bulk upload), PDF
  payslips (HTML prints to PDF from a browser), insurance and other tax reliefs beyond a fixed `credit`.

## Layout

```
api/          routes.py and schemas.py (HTTP only)
services/     employees, pay_setup, statutory_rules, attendance, leave, payroll, outputs, access
domain/       rules (statutory rule format and methods), payroll (the calculation), time, identity, payslip_print
repository/   models.py and people_repo.py
events.py     till.opened / till.closed -> attendance
public.py     the only file other units may import (nothing yet)
```
