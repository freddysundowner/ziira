# Data protection and privacy

**This is engineering documentation, not legal advice, and it is not tied to any one country's law.** Ziira is a
*processor* of each business's data: the business (the *controller*) decides what it must keep, for how long, and
whether to grant a request. Ziira gives it the tools to find, export, correct and erase a person's data, to keep
a record of doing so, and to apply retention periods it chooses. Which law applies, which records must be kept, and
for how long are the business's decisions, taken with its own advisers, and recorded as **settings** (data), never as
code. If your law asks for something these tools do not do, tell us rather than assuming they do.

## Contents

1. [What is stored where (data map)](#1-what-is-stored-where-data-map)
2. [Handling a request, step by step](#2-handling-a-request-step-by-step)
3. [What is anonymised and what is kept](#3-what-is-anonymised-and-what-is-kept)
4. [Retention settings and the daily job](#4-retention-settings-and-the-daily-job)
5. [Permissions, approval and audit](#5-permissions-approval-and-audit)
6. [API reference](#6-api-reference)
7. [For module authors: the `kernel.personal_data` socket](#7-for-module-authors-the-kernelpersonal_data-socket)
8. [Processor duties: breach response and DPA checklist](#8-processor-duties-breach-response-and-dpa-checklist)
9. [What is not covered, and what is untested](#9-what-is-not-covered-and-what-is-untested)

## 1. What is stored where (data map)

Every business has its own database (decision 0004), so one business's data is never in another's. Inside a business,
personal data sits in these places. "Free text" means staff typed it, so it can hold anything.

| Unit | Table (schema) | Personal data | Kept after erasure? |
|---|---|---|---|
| Kernel | `kernel.app_user` | Name, email, phone, sign-in status, last login | Replaced; sign-in closed |
| Kernel | `kernel.user_phone`, `kernel.user_mfa`, `kernel.user_session` | Verified phones, authenticator secret (encrypted), sign-in devices (id, name) | Deleted / closed and names removed |
| Kernel | `kernel.notification` | Recipient (email or phone), subject, text of every message sent | Recipient masked, subject and text replaced; the fact of sending stays |
| Kernel | `kernel.notification_optout` | Addresses that asked not to be contacted | **Kept**: it is how the business honours the request |
| Kernel | `kernel.audit_log` | User ids, device ids, IP addresses, and what was typed when records were made (a name, an email) | **Kept**: immutable by design |
| Kernel | `kernel.privacy_request` | The subject of each request and what it found | Subject masked once an erasure completes |
| Master database | `master.login_directory` | A keyed hash of each user's email and phone (no raw values) | The user's entries are removed |
| CRM | `crm.customer` | Name, phone, email, tax number | Replaced; code, credit limit, terms, status stay |
| CRM | `crm.customer_contact` | Name, phone, email, role | Replaced |
| CRM | `crm.lead` | Name, business, phone, email, lost reason | Replaced |
| CRM | `crm.activity` | Follow-up notes (free text) | Replaced with `[removed]` |
| POS | `pos.sale`, `sales_invoice`, `customer_receipt`, `sales_document`, `customer_refund`, `sales_return` | A customer **id** only (no name or number); free text in invoice and quotation notes, receipt references | Documents, numbers, dates, amounts stay; notes removed where the document may still be edited |
| Purchasing | `purchasing.supplier` | Name, phone, email, tax number | Replaced; supplier set inactive; code stays |
| Purchasing | `purchasing.supplier_bank_account` | Account holder, bank, account number (encrypted) and mask | Emptied |
| Payments | `payments.external_transaction` | Payer name, masked phone, one-way phone fingerprint (the raw payload is stored with names and numbers hidden) | Name and fingerprint removed, mask replaced; receipt numbers and amounts stay |
| Payments | `payments.payment`, `payment_intent` | Phone fingerprint, masked phone | Fingerprint removed, mask replaced |
| People | `people.employee` | Name, national id (encrypted), tax number, registration numbers, phone, email | See section 3 |
| People | `people.employee_bank_account` | Bank, account number (encrypted) and mask | See section 3 |
| People | `people.attendance`, `leave_request`, `employment_terms`, `payslip`, `payroll_run` | Time worked, leave (with free-text reasons), pay | Amounts and dates stay; leave reasons and notes removed |
| Finance / Inventory | `finance.journal_*`, `inventory.stock_movement` | Ids of parties only; no names | Never touched (immutable) |

Secrets (passwords, authenticator secrets, bank account numbers) are stored hashed or encrypted and are **never**
included in an export.

## 2. Handling a request, step by step

You need the permission `privacy.manage` (only the Owner role has it by default; give it deliberately, to the person
who acts as the business's privacy contact).

1. **Verify who is asking.** Ziira cannot do this for you. Record how in the request's `notes`.
2. **Record the request.** `POST /api/v1/privacy/requests` with `company_id`, `request_type` (`access`,
   `correction` or `erasure`), the `subject` (what the person gave: an email, a phone number, an id number or a name) and
   optionally `received_on`. It gets a number (`DSR-...`) and a due date, `privacy_response_days` after it was received
   (default 30; set what your law or policy requires). Requests past their due date are flagged in the exceptions inbox
   by the daily job.
3. **Search.** `POST /requests/{id}/search`. Every unit that holds personal data looks and the results are kept on the
   request. An email, a phone number or an id matches **exactly**; a name matches loosely and is marked **possible**.
   Look at each possible match and decide whether it is the same person.
4. **Access**: `POST /requests/{id}/export` returns one JSON bundle of what is held. Only exact matches are included
   unless you list the `record_ids` of possible matches you have confirmed. **Every export is written to the audit log
   as a `data_export`** (who, when, from which channel, how many records of which units; never the data itself). Send
   the bundle to the person by a channel you trust, then `POST /requests/{id}/close` with `completed` and a note.
5. **Correction**: correct the data in the unit's own screens (customer, employee, supplier). Use the export to show
   what was held, then close the request with a note of what changed.
6. **Erasure**: `POST /requests/{id}/erase` with:
   - `confirm_subject`: the subject typed again (a guard against erasing the wrong request),
   - `reason`: why (at least a few words),
   - optionally `record_ids` (exact matches by default; add confirmed possible matches).
   If the company setting `privacy_erasure_needs_approval` is on (the default) the request waits for **a second
   person**, through the approval matrix (document type `privacy.erasure`). Add a rule first
   (`POST /api/v1/approvals/rules` with `doc_type: "privacy.erasure"` and the role that may approve, for example
   Owner); with no rule the erase call is refused and tells you so. The person who asked cannot approve their own request.
   When approved, each unit anonymises its records and the request records exactly what changed and what was kept and
   why. **This cannot be undone.** If the approval is rejected nothing changes and the request is back in your hands.
7. **Tell the person what was done**, including anything kept and why (the request's `outcome` has the wording).
   Close the request. Records that must stay for a period are listed with the date they can be erased: raise a new
   request then.

Things to settle before erasing a customer: outstanding balances (the invoices stay and still name the customer by code,
but you may want to collect or write them off first), and whether the person is also a supplier or employee (the search
finds every role they have).

## 3. What is anonymised and what is kept

"Anonymised" means identifying fields are replaced with a placeholder (`[erased] customer CUS-000012`, `Erased user`) or
emptied. The record itself stays when something else points at it, so posted documents keep working.

**Always kept** (they hold no identity once the fields above are replaced): document numbers, dates, amounts, tax
amounts, quantities, payment methods, provider receipt numbers, the journal, stock movements and the audit log. The
ledger is never touched, so it still balances.

**What each unit does**

- **CRM**: customer, contact and lead identifying fields replaced; follow-up notes replaced. Credit limit, terms,
  status and the customer code stay.
- **POS**: finds the person through the customer CRM found. Removes the free-text notes on invoices and quotations that
  can still be edited. Cancelled invoices cannot be edited and keep their note; a receipt's reference is the payment's
  own reference and stays.
- **Purchasing**: supplier name, phone, email, tax number and bank details replaced; supplier set inactive. **While
  the business still owes the supplier**, only phone and email are removed and the name and payment details are kept
  (needed to pay them); the outcome says so.
- **Payments**: payer name and phone fingerprint removed from mobile money transactions, the phone mask replaced.
- **People**: payroll and employment records are the kind a business normally has to keep. The business states the
  period with the company setting `retention_employee_records_years` (default 7; 0 means no minimum). The rule is:
  - *still employed*: **refused** ("still employed");
  - *employment ended, inside the period* (counted from the end of employment or the last approved/paid payslip,
    whichever is later): **partial**. Phone, email and free-text leave reasons and notes are removed; name, ids, payment
    details and pay records are kept, with the reason and the date they can be erased;
  - *after the period*: **anonymised**. Name, national id, tax number, registration numbers, contact and bank details
    are removed; payslips keep their amounts and the employee number.
- **Kernel users**: name, email, phone, password and authenticator secret removed, devices closed, the account disabled
  and its login removed from the login directory. You cannot erase the account you are signed in with or the
  business's only owner.
- **Messages sent**: the recipient is masked and the subject and text replaced; messages still waiting are cancelled. The
  do-not-contact entry for the address stays.

**Not in your power to change from here**: the audit log is immutable. It records ids, and the name or email typed when
a user or employee was created. If your law needs that removed too, say so before relying on the retention figures.

## 4. Retention settings and the daily job

Company settings (`PATCH /api/v1/companies/{id}/settings`, permission `settings.manage`). All are data a business
sets; none is a statement of any country's law.

| Setting | Default | Meaning |
|---|---|---|
| `privacy_response_days` | 30 | Days from receipt to the due date of a request |
| `privacy_erasure_needs_approval` | on | A second person approves an erasure (document type `privacy.erasure`) |
| `retention_notifications_days` | 0 | Messages keep recipient and text this many days, then both are masked (0 keeps them) |
| `retention_audit_years` | 7 | The period the business states it keeps its audit trail and financial records. **The audit log is never deleted**; this is documentation shown in the retention view |
| `retention_employee_records_years` | 7 | Payroll and employment records of a former employee are kept this long (0: no minimum) |
| `retention_inactive_customers_years` | 0 | A customer who is not active and untouched this long is put in the exceptions inbox for review (0: off) |

The recurring task `privacy.apply_retention` runs once a day per business in `ziira worker`; run it now with
`.venv/bin/ziira run-task <tenant> privacy.apply_retention`. It:

- masks the recipient, subject and text of finished messages older than `retention_notifications_days` (never one still
  waiting to be sent) and writes the count to the audit log (`retention_mask`, no addresses or text);
- puts records past a review period (inactive customers) in the exceptions inbox, once per unit, for a person to review
  and erase through a request if no longer needed;
- flags requests past their due date.

It never touches the journal, stock movements or the audit log. `GET /api/v1/privacy/retention?company_id=...` shows
what every unit keeps, for how long, what happens at the end, how many records are past the period right now, and the
tables that are never deleted.

## 5. Permissions, approval and audit

- Permission `privacy.manage` (company scope). Nothing else grants access to these endpoints. A request for a company
  you do not manage is refused, and another business's requests cannot be read (separate databases).
- Audit entries (hash-chained, immutable) for: `create`, `search`, `data_export`, `erase_requested`, `erase`,
  `erase_rejected`, `completed` / `refused`, `retention_mask`. They carry a masked form of the subject
  (`2547****678`, `m***@example.com`), never the full subject, and for an erasure the counts, what changed and what was
  kept.
- The request itself stores the full subject until an erasure succeeds, then only the masked form. Anything staff
  typed in `notes` stays; do not put more personal data there than needed.

## 6. API reference

| Method and path | Purpose |
|---|---|
| `POST /api/v1/privacy/requests` | Record a request (`company_id`, `request_type`, `subject`, `notes?`, `received_on?`) |
| `GET /api/v1/privacy/requests?status=&company_id=` | List, oldest due first |
| `GET /api/v1/privacy/requests/{id}` | One request: status, due date, what was found, outcome |
| `POST /api/v1/privacy/requests/{id}/search` | Ask every unit what it holds |
| `POST /api/v1/privacy/requests/{id}/export` | JSON bundle (`record_ids?`); audited as `data_export` |
| `POST /api/v1/privacy/requests/{id}/erase` | Anonymise (`confirm_subject`, `reason`, `record_ids?`); irreversible; may wait for approval |
| `POST /api/v1/privacy/requests/{id}/close` | Finish by hand (`completed` or `refused`, with a note) |
| `GET /api/v1/privacy/retention?company_id=` | What each unit keeps and for how long |

Statuses: `open` -> `in_progress` (searched, exported, or waiting for approval) -> `completed` or `refused`.

## 7. For module authors: the `kernel.personal_data` socket

A unit that stores data about people plugs a provider into the socket from its own `hooks.py` and lists
`kernel.personal_data` under `[extends] implements` in its manifest (`tests/test_architecture.py` checks the two agree):

```python
@provides("kernel.personal_data")
class MyPersonalData(PersonalDataProvider):
    name = "myunit"
    def find(self, session, company_id, subject) -> list[PersonalRecord]: ...
    def export(self, session, record) -> dict: ...
    def anonymise(self, session, record, reason) -> Outcome: ...
    def linked(self, session, company_id, found) -> list[PersonalRecord]: ...   # optional
    def retention(self, session, company_id) -> list[RetentionRule]: ...        # optional
```

All names come from `ziira.sdk`. Rules:

- `find` matches `subject.email`, `subject.phone` (international digits), `subject.identifier` (a tax or national id,
  spaces and dashes removed, upper case) **exactly** and `subject.name` loosely, returning `match="possible"` for names.
  Helpers: `sql_digits`, `sql_identifier`, `like_pattern`, `json_rows`, `json_one`. Skip records whose name already
  starts with `PLACEHOLDER`.
- `linked` returns your records that hang from what other units found (look at `record.source` and `record.kind` as text,
  never at their tables): POS finds a customer's documents this way.
- `export` returns JSON-able fields and never secrets (password hashes, keys, ciphertext).
- `anonymise` replaces identifying fields, keeps what posted documents need, **never touches an immutable table**, and
  returns an `Outcome`: `anonymised`, `partial` (say what you kept with `Kept(what, why)`), or `refused` with a message.
  Read the business's retention period from a company setting (`company_setting`), never from a constant.
- `PersonalRecord.record_id` must be unique across providers (use `uuid5` when you key by something other than your own
  row id) and `ref` is your private pointer (erased with the rest).

## 8. Processor duties: breach response and DPA checklist

The business is the controller; Ziira acts on its instructions. A starting point, to be completed with your own
counsel and adapted to the law that applies to you.

**Personal data breach response (skeleton)**

1. *Detect and contain*: revoke affected sessions (`users` screen, or erase the sign-in), rotate API keys, rotate
   `ZIIRA_SECRET_KEY` (signs tokens) if token theft is possible. Rotating `ZIIRA_CREDENTIALS_KEY` locks every tenant
   out; plan it as a migration, not an emergency step.
2. *Assess*: what data (use the data map above), whose, how many, whether it was encrypted (passwords are hashed; bank
   and national ids and credentials are encrypted at rest; names, emails and phones are not), and the likely harm.
3. *Record*: keep an internal note of facts, effects and actions, whether or not it must be reported. The audit log
   and `data_export` entries help to establish what was read or exported.
4. *Notify*: the controller tells the regulator and the people affected within the deadline that applies to it. A
   processor tells the controller without delay. Decide who calls whom before an incident happens.
5. *Learn*: fix the cause, add a test, update this document.

**DPA checklist** (what a data processing agreement between the business and Ziira normally covers)

- [ ] Subject matter, duration, nature and purpose of the processing; types of data and of people
- [ ] Processing only on documented instructions of the business
- [ ] Confidentiality of the people who handle the data
- [ ] Security measures (access control by permission, row-level isolation per business, encryption of secrets,
      immutable audit trail, backups; see the technical specification section 18)
- [ ] Sub-processors (hosting, email and SMS gateways, payment providers) listed, with how changes are notified
- [ ] Help with data subject requests (this document), assessments and breach notification
- [ ] Return or deletion of all data at the end of the contract (`ziira drop-tenant` deletes a business's database;
      take an export first)
- [ ] Audits and inspections
- [ ] Where data is hosted and any transfers across borders

## 9. What is not covered, and what is untested

- **Backups** contain erased data until they expire. Erasure is not applied to backups; keep a backup retention period
  consistent with what you tell people, and re-apply erasures when restoring (the privacy requests table lists them).
- **Free text** that staff typed elsewhere (product descriptions, exception notes, document notes in units not listed
  above, uploaded files) is not searched. The search finds what is recorded in the fields in the data map.
- **Names are not unique**: a name search only ever produces *possible* matches that a person must confirm.
- **Audit log**: not erasable; see section 3.
- **Other systems** (an email provider's logs, the SMS gateway, a payment provider) hold their own copies; erasing in
  Ziira does not erase there.
- The tests (`tests/test_privacy.py`) run against a real database through the API for every unit above. They have not
  been checked against any regulator's requirements; that review is the business's.
