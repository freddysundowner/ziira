# Companies and branches after registration

Registration makes one company with one branch. Settings > Organisation (`/admin/organisation`, permission
`organisation.manage`, the Owner by default) is where a business grows: add a company, add a branch, edit them, close a
branch that is no longer used.

## What it does

| Action | API | Rules |
|---|---|---|
| List with counts | `GET /api/v1/organisation` | The companies you manage (all for a tenant-wide grant), every branch (closed ones too) with `counts`: `users` (people holding a branch-scoped role there) plus what units report: `devices` (POS), `locations` (Inventory). |
| Add a company | `POST /api/v1/companies` | Tenant-wide grant only. Name (unique, any case), currency (three letters), country, tax number, time zone, tax-registered flag, optionally the first branch (code and name). The calling code of the first company carries over. Its chart of accounts, journals and price lists are made the first time they are needed, so nothing is set up in other units. |
| Edit a company | `PATCH /api/v1/companies/{id}` | A grant over that company is enough. **The currency cannot change once the company has postings**: units say so through `currency_locks` (sales, stock movements, journal entries); the answer is 409 and names them. Add a new company in the other currency instead. |
| Add a branch | `POST /api/v1/companies/{id}/branches` | Code (1 to 10 letters, digits, `-` or `_`, stored in capitals, unique in the company; it appears in document numbers) and name; address and phone optional. |
| Edit a branch | `PATCH /api/v1/branches/{id}` | A new code applies to documents numbered from then on. |
| Close / reopen a branch | `POST /api/v1/branches/{id}/deactivate`, `/reactivate` | Refused (409, with the reasons) while the branch has an open till, stock transfers in transit, transfers, adjustments or counts not posted, or sales documents still drafts or waiting for approval; and refused for a company's last open branch. History is kept. A closed branch is left out of the pickers (`GET /api/v1/companies`) and takes no new tills, devices or locations (`check_branch_open`). |

Everything is audited (`create`/`update`/`deactivate`/`reactivate` on `kernel.company` and `kernel.branch`). A role held over one
company manages that company only; a role held over one branch cannot manage the company (the Owner's tenant-wide grant can do
all). Another business's ids answer 404.

## For unit authors

Implement `BranchUsageProvider` (`ziira.sdk`) in the unit's `hooks.py` with `@provides("kernel.branch_usage")` and list
`kernel.branch_usage` under `[extends] implements` in the manifest. See `ziira/modules/pos/organisation.py`. Keep the queries
cheap: `branch_counts` runs for every branch on each list.

## After a kernel upgrade

`ziira install` gives the Owner role of every business any permission the kernel gained since (as it already did for
units), so existing businesses get `organisation.manage` without a migration.
