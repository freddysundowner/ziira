# Plan: simpler Intelligence in the app, and a customer assistant on WhatsApp

Status: plan, not built. Written 2026-10-16 at the owner's request. Rule for both: **nothing is removed**; simple by
default, everything powerful still one step away.

## Part A: Simplifying Intelligence in the app

### Problem
Intelligence has the right power but too much vocabulary and noise: checks, baselines, findings with five statuses, four
action levels, automation rules, coverage, approvals. The demo shows "57 open findings" at once. An owner needs three
things: the morning summary, what to look at today, and a way to ask.

### Principles
1. **Progressive disclosure**: three layers: *Simple* (default), *Advanced* (tuning, rules, levels), *Expert* (check codes,
   parameters, evidence ids, API). Nothing is deleted; each layer is a click or a toggle away.
2. **Good defaults, two-minute start**: turning Intelligence on works without configuration.
3. **Plain words in the UI**, technical names kept as tooltips, in the glossary and in Expert view.
4. **Less noise, not fewer checks**: group, rank and cap what is shown; every check still runs.

### Plain-word vocabulary (UI only; code and API names stay)
| Today | Simple layer says |
|---|---|
| Findings | Things to look at |
| Severity high / medium / low | Urgent / Soon / Worth a look |
| Baselines | Your normal |
| Checks | What Ziira watches |
| Coverage | What Ziira can see |
| Action levels 1-4 | How much Ziira does for you: Watch / Ask / Prepare / Act for me |
| Auto rules | Things Ziira may do for you |
| Dismiss | Not a problem |

### Changes
1. **Turn it on in one screen**: pick what matters (Cash and sales, Stock, Customers who owe, Suppliers, Staff and payroll,
   Books) as toggles; each maps to the real check groups; a recommended preset per edition and business size; choose when
   and where the daily summary arrives; finish with a sample "thing to look at" so the first screen is not empty.
2. **One Today page** for Intelligence: the summary sentence, the top 5 things to look at as cards, an Ask box. Everything
   else sits under four clear places: *Things to look at* (full list and filters), *What Ziira watches* (tuning),
   *Actions* (suggestions, approvals, rules), *Settings* (channels, brief, how much Ziira does).
3. **A better card**: plain headline, "Why it matters", three key facts, "What to do next" (guidance per check), three
   buttons (Look into it, Give to someone, Not a problem). Technical detail behind "Show details".
4. **Noise control**: group similar findings by theme and branch ("14 sales cancelled after 9pm at Ruiru" as one card),
   a daily cap on what is pushed, snooze, and "this is normal" feedback that tunes the unusual-threshold for that business.
5. **Tuning without jargon** (Advanced): sentences with a small control: "Flag customers who are late by [30] days",
   instead of parameter names. Reset to recommended.
6. **Levels explained by outcome**: each mode shows what changes, with an example, and what it will never do (never moves
   money). Levels 3 and 4 and all rules stay, with Owner-only control as built.
7. **Proof of value** (only where the data supports it): "This month Ziira pointed out 12 things; 7 were acted on."
8. **Empty and first-run states** designed: tour with a sample finding; "nothing to look at today" feels good.

### Delivery
Phase 1 vocabulary + Today page + card + grouping (the visible win). Phase 2 one-screen setup and presets + tuning
sentences. Phase 3 feedback loop and value summary. Test with five real owners before Phase 3.
Measure: time to first useful finding, share of findings acted on, "not a problem" rate, alert opt-outs.

## Part B: Customer assistant on WhatsApp (add-on feature, off by default)

### What it is
A small, tightly limited assistant that answers customers who message the business's connected number, only from things
the business approves. Staff keep a normal inbox and can take over at any moment.

### Scope (first version)
- Opening hours, address, contact.
- "How do I pay?" (the business's own payment instructions).
- "What do I owe?" and "Send my statement" for the customer's own account.
- "Where is my order?" (status of their own open orders/invoices).
- "I will pay on Friday": records a promise to pay on the account and pauses reminders until then.
- "Talk to a person": hands over to staff with the conversation so far.
- STOP / opt-out always works.

### Safety rules (non-negotiable)
1. **Identity**: the sender's number must match exactly one customer (normalised phone on the CRM record). No match or more
   than one: a generic reply and a staff hand-off, nothing about any account.
2. **Sensitive answers need a challenge** (configurable): for example the last invoice number or last four digits of a
   registered ID. Protects against SIM swaps and shared phones.
3. **Read-only, customer-scoped tools**: the assistant calls a small allow-list of tools that return only that customer's
   own data. It cannot reach other customers, prices, costs or books. It never moves money and never changes a record
   except the promise-to-pay note.
4. **A model only understands and phrases; numbers come from the tools** (same rule as Ask Ziira). Version 1 can be
   rules/keywords only; a model is optional and consented.
5. **Consent and limits**: first-contact notice and consent captured; daily message cap per customer; respects business
   hours and the 24-hour window (templates outside it); kill switch; full conversation log with retention settings.
6. **Hand-off over guessing**: low confidence means "let me get someone" and a task for staff.

### Staff side
An Inbox (conversations, who is waiting, take over and reply as a person, assign, canned replies), a link from the customer
page and from "Who owes us", and settings: on/off, hours, allowed topics, challenge type, who receives hand-offs,
languages, test mode ("try it with my own number").

### Delivery
1. Identity, hours/payment info, balance and statement, hand-off, inbox, STOP. (Needs inbound support in the Lead Intel
   add-on tested live.)
2. Promise to pay, order status, payment link using the business's own payment provider.
3. Optional model-assisted understanding; more languages.

### Risks
Not yet tested live with Lead Intel; WhatsApp business-initiated message rules and opt-in; privacy law on automated
messages; cost of model calls (optional). Each is handled by off-by-default, consent, limits, and a live test checklist
before any real customer is messaged.
