# Channels: email, SMS and chat services (WhatsApp through Lead Intel)

How Ziira reaches people, and how people answer. Read `docs/notifications.md` first for the basic queue (`send_notification`); this
page is the layer above it: **the channel registry, message templates and their approval, each person's channel and quiet hours,
verified numbers, replies that act, and the Lead Intel plugin** that provides WhatsApp.

```
unit code ── notify_user / notify_user_templated / send_templated ──▶ kernel/messaging.py   who, which channel, when (quiet hours)
                                                                          │ asks kernel/channels.py which channels exist
                                                                          ▼
                                    kernel/templates.py  ◀── message_templates.json (wording, en + sw, as data)
                                                                          │
                                                          kernel/notifications.py  queue ─▶ job ─▶ NotificationChannel.send
                                                                          │                        (messaging, leadsintel plugins)
inbound: provider webhook ─▶ plugin verifies ─▶ kernel/inbound.py route ─▶ STOP / unknown / a user's command ─▶ handlers
                                                                                                  (intel: Approve / Reject / Why?)
```

## The channel registry: a channel exists only where its provider is enabled

There is no fixed list of channels. Each provider (the `kernel.notification_channel` extension point) declares **the one channel it
offers** and what it can do:

| Attribute | Meaning |
|---|---|
| `channel`, `channel_label` | the channel's name (`email`, `sms`, or the provider's own) and how screens name it |
| `supports_templates` | the provider approves message templates (needed to start a conversation) |
| `supports_buttons` | reply buttons (`Outgoing.mode == "buttons"`) |
| `supports_inbound` | replies arrive (`route_inbound`): a person's number on it must be verified before anything is done on their word |
| `window_hours` | conversational: a free-form message only within this many hours of the person's last message; templates otherwise |
| `development_only` | never offered in production (the fakes) |

`kernel/channels.py: available(session)` is the list for a business: the channels with a provider belonging to a unit **enabled for that
business**. Email and SMS are channels only while the `messaging` plugin is on; WhatsApp only while `leadsintel` is on. Everything is
built from it:

* `GET /api/v1/notifications/channels/available[?company_id=]` returns `{channel, label, providers, configured, supports_*, window_hours}`
  for each. **The web app builds every channel select from it** (`useChannels` in `frontend/src/sdk/channels.ts`).
* Validation uses it: company settings `intel_alert_channel` and `reminder_channel`, a person's preferences, CRM do-not-contact,
  channel set-up and test sends, brief schedules and "send now" all refuse a channel the business does not have, with
  *"Channel 'x' is not available for this business (switch on the plugin that offers it). Available: sms, email"*.
* **Switching a plugin off keeps what was set and uses the next channel.** A setting, a preference or a queued message that names a
  channel which is gone is not an error: delivery goes by the next channel the person has (`plan_for_user` skips unavailable names and
  then only uses channels that are set up); a queued message whose provider is gone falls back like any refused message, so nothing is
  dropped; the UI shows the stored value as "(not available)" with a warning. Switch the plugin on again and it works again.
* The platform's own code never names a chat service: `tests/test_channel_registry.py` scans `ziira/kernel`, `ziira/modules` and `ziira/sdk`
  (and the shared web screens) for it. Intelligence asks the channel layer for "the person's preferred available channel" and for a
  *capability* (`capability="buttons"`), never for a name. A command by chat runs with the audit channel `chat`; the provider's own
  channel name is in the audit entry.

## The rules that hold

* **A message is queued in the caller's transaction and sent by the worker** (never in a request). One record per attempt; a
  message that is sent stays sent. Retried with growing delays on an outage; a refusal that will not pass moves on at once.
* **The conversation window.** On a channel with `window_hours`, a free-form message (text or reply buttons) may be sent only within that
  time of the person's last message to the business (`kernel.contact_window`, set by every inbound message). Outside it only an
  **approved template** may be sent. The kernel decides this when it sends, not the provider.
* **Templates must be approved.** A business has a row per shipped template and language for each channel that needs them
  (`kernel.message_template`: draft, submitted, approved, rejected). A message that needs a template which is not approved is
  *refused* and falls back to the next channel. Nothing waits silently.
* **Fallbacks.** A message carries an ordered list of other ways to reach the person. It is tried on the next channel when the
  first is not available, has no channel set up, is not approved/open, is refused for good, or gave up after its retries. The first record
  says what happened ("... sent by sms instead") and no exception is raised, because the person was reached. If there is nothing left,
  the message is skipped and the exceptions inbox is told once.
* **Do not contact.** Opt-outs apply per recipient and channel. Someone who refused one channel is reached by the next; someone who
  refused every channel (a STOP, or a do-not-contact without a channel) is left alone and the fallbacks are not tried.
  An inbound **STOP** (or `UNSUBSCRIBE`, `ACHA`) adds the sender to the do-not-contact list for every channel, whoever they are.
* **Quiet hours defer, never drop.** A person's quiet period (company time zone) delays a message to its end. A critical alert
  passes only if the person allowed that.
* **No country in code.** Currency, calling codes and time zones are company data; the wording is data in each language.

## Staff: channel per kind, quiet hours, verified number

Each person chooses (My account > Notifications; `GET/PUT /api/v1/notifications/me/preferences`):

| Kind | What it covers | Used by |
|---|---|---|
| `alerts` | urgent findings, nudges, "please explain" | `intel.alerts`, `nudges`, level-2 asks |
| `brief` | the daily and weekly brief | `command.briefs` |
| `approvals` | a suggestion waiting for their decision | `intel.approver_messages` |

Each is `default` (the business's own setting: `intel_alert_channel`, the brief schedule's channel, or, for approvals, a channel with
reply buttons if the business has one), the name of a channel the business has, or `app` (nothing outside the app). The chosen
channel comes first, then the business's default, then the person's other channels that the business has set up. Quiet hours (`quiet_start`/`quiet_end`, may cross
midnight), "let critical alerts through", and the language of messages (`en`, `sw`) are in the same record
(`kernel.user_notification_pref`).

**Numbers must be verified** (only offered when a channel with `supports_inbound` is available). A number counts only after its owner
types back the code sent to it (`POST /me/verified-number`, `POST /me/verified-number/verify`; 15 minutes, 5 tries). The code goes by
the first channel the business has set up that reaches the number (the reply channel, then SMS), and by email last: an email
code proves only that the person controls their account, not the number. Only a verified number is messaged on a reply channel
and only a verified number is ever matched to a user: otherwise anyone who can edit a user's phone could approve things as the owner. One
verified number per person per business.

## Templates

`ziira/kernel/message_templates.json` ships six templates with English and Swahili wording: `daily_brief`, `urgent_alert`,
`overdue_reminder`, `payment_due`, `action_proposal` (with Approve / Reject / Why? buttons) and `verification_code`. `{name}`
placeholders are the variables; they become `{{1}}`, `{{2}}` ... for the provider, in the order of the template's `variables`.
SMS and email use the same wording directly (no approval). Adding a template or a language is editing that file; adding a
language also needs it in `templates.LANGUAGES`.

`GET /api/v1/notifications/templates` lists the business's rows; `POST .../templates/submit` sends drafts and rejected ones to the
provider; `POST .../templates/sync` (and the recurring `kernel.sync_templates`, every 30 minutes) records the provider's decisions.
Provider template names are `ziira_<code>`. A provider supports this by setting `supports_templates = True` and implementing
`submit_template` and `template_state` on its `NotificationChannel`.

## Reply to act (Intelligence level 3)

When a suggestion is made (`intel.actions._propose`), each person who holds the provider's `needs_permission` for that company and
branch is messaged on their `approvals` channel; on a channel with `supports_buttons` (WhatsApp, once Lead Intel is on) the message carries buttons `approve:<id>`, `reject:<id>`, `why:<id>`
(as quick-reply buttons of the `action_proposal` template when the window is closed). Suggestions an owner's rule has already
carried out (level 4) are not announced.

An inbound message goes through `kernel/inbound.route`:

1. the sender's window opens; 2. STOP words opt out; 3. a number that is not exactly one active user's **verified** number gets
**nothing back** (the message is only stored); 4. a verified user is limited to 30 commands per 10 minutes and the message is run by
the first `kernel.inbound_command` handler that understands it, **as that user** (their permissions, audit channel `chat`):

* **Approve** = `actions.approve` as them (Core permissions and the owning unit's rules apply; a suggestion no longer open, a
  closed finding, or a missing permission is refused with a short message). The action log, the finding's history and the audit log
  record the channel `chat`. Tapping twice does nothing the second time.
* **Reject** = `actions.reject` with the reason "Declined by reply in chat".
* **Why?** answers from the suggestion itself (description, the finding, the facts): no AI involved.
* **Free text** is a question for Ask Ziira. It is queued (`intel.channel_question`) and answered by the worker with no
  transaction open (`intel.answer_channel_questions`, every minute) as that person, within their permissions, and the answer is
  sent back on the same channel. If the assistant is off the person is told so.
* Anything else gets one short help message. Every command is audited (`channel.command`, outcome, never the free text).

Core's own approval requests (`kernel.approval`: leave, payroll, discounts) are **not** answerable by reply yet: only
Intelligence suggestions are. Add a handler on `kernel.inbound_command` to do it.

## Customer reminders

`pos.send_payment_reminder`, `POST /invoices/{id}/send-reminder` and the daily chase accept any channel the business has (also the
company settings `reminder_channel` and `intel_alert_channel`). The template carries the customer's name, the invoice number, the
amount **in the company's currency**, the business name and the due date (`overdue_reminder` once past due, `payment_due`
before). If the business has SMS and email set up they are the fallbacks, in that order. A pay link or instruction is not included:
the payments unit offers none yet.

## The Lead Intel plugin (`ziira/plugins/leadsintel`)

Provides **only** the `whatsapp` channel (provider `leadsintel`, label "WhatsApp"; it declares templates, buttons, replies and a 24-hour window). Lead Intel is not an SMS provider for Ziira: SMS comes from the `messaging` plugin. API reference used: https://leadsintel.net/developers.html
(read 2026-10-15; base `https://app.leadsintel.net/api`).

**Setting up** (Settings > WhatsApp through Lead Intel, permission `settings.manage`; the page exists only while the plugin is enabled for the business):

1. *Platform key* (`PUT /api/v1/plugins/leadsintel/key`): checked with a harmless connection lookup (Lead Intel answers 404 for
   an unknown number and 401 for a wrong key), stored encrypted with a generated webhook secret. Never returned or logged.
2. *A new number* (`POST .../whatsapp/connect`): Lead Intel's assisted setup with Meta (`externalPlatformTenantId` is the Ziira
   tenant, `externalConnectionId` a new id, the webhook address `https://<public base>/api/v1/plugins/leadsintel/webhook/<token>`).
   The screen polls `POST .../whatsapp/refresh` (requested, awaiting code, connected, then the connection must be `active`).
   *A number already on Lead Intel* (`.../existing`, `.../claim`, `.../claim/verify`): Lead Intel itself sends a code by SMS to the number (part of its documented setup, not Ziira's SMS channel). `cancel` and
   `disconnect` are there too. The public base address must be https (`ZIIRA_PUBLIC_BASE_URL`).
3. *Test message* and *Message templates* (submit all, check status) on the same screen; *Replies* lists what people wrote.

**Sending** uses `POST .../connections/{tenant}/{connection}/send` with `Idempotency-Key: ziira-<notification id>-<mode>`
(so a retry after a timeout can never send twice, and a key is never reused with different content). 202 means accepted, not
delivered: delivery arrives on the webhook as `statuses` and moves the message to delivered/read/failed (never backwards).
Mapping: outage, 408/425/429/5xx raised (retried); 400/401/403/404/409 permanent (next channel); 502 `send_failed` on a free-form
message is permanent ("the 24-hour window may be closed"), on a template it is retried.

**Receiving** (`POST .../webhook/<token>`, public): the token holds the tenant, so an unknown token and a bad signature get the same
`401`. Then, in this order and before reading anything from the body: timestamp within 5 minutes, signature
`HMAC-SHA256(webhook secret, "<timestamp>.<raw body>")` in lower-case hex compared in constant time, event id recorded (a repeat is
acknowledged and does nothing), phone number id matched. Then `messages[]` are stored and routed, `statuses[]` applied. Everything
runs in one transaction: a failure is a `500` and the event id is not kept, so Lead Intel retries. `202` is returned on success.

### What is verified and what is not

Verified against Lead Intel's published page: the base address, the key header, assisted setup, lookup, claim and verify, the
connection get/patch/delete, the send endpoint and its message types and limits, the idempotency key, the error codes, the webhook
headers, signature and payload (`messages[]`, `interactive.button_reply.id`, `button.payload`, media `downloadUrl`).

**Not documented by Lead Intel; guessed, and all in `ziira/plugins/leadsintel/unverified.py`** (each marked `# UNVERIFIED`):

| What | Assumed |
|---|---|
| Creating a template | `POST .../whatsapp/connections/{tenant}/{connection}/templates` in Meta's format (`name`, `language`, `category`, `components`: BODY with examples, BUTTONS quick replies) |
| Template status | `GET .../templates?name=&language=` returning `{id, status: PENDING / APPROVED / REJECTED ..., reason}` (or a `templates` list) |
| Template send components | Meta's `components` (body `parameters` of type text; button `sub_type: quick_reply` with a `payload` parameter) |
| Delivery reports | a `statuses[]` array of Meta's shape (`id`, `status`, `errors[].title`) in the same webhook |
| Template wording limits | Meta's rules (no newlines in variables, none at the start or end) are applied only as far as `clean_value` squashes whitespace |

Until Lead Intel confirms these, templates can be created and approved in Lead Intel's own screens with the names `ziira_<code>`
(then "Check status" will pick them up only if the status shape matches).
**Nothing was run against the real service. Live testing is required** (a Lead Intel sandbox account, a test number, the 24-hour
window, a real template approval, the webhook with the real secret and signature).

## Adding a provider

Implement `NotificationChannel` for the channel (`send(message, secret, config) -> SendResult`; raise for a failure that may pass,
return `permanent_failure=True` for one that will not), register it with `@provides("kernel.notification_channel")` in the
plugin's `hooks.py`, and keep its keys in the credential store (`store_credential`, config `{"provider": name, ...}`). For a conversational channel
read `Outgoing.mode` (`text`, `buttons`, `template`) rather than deciding the window yourself, set `supports_templates` and
implement the two template methods, and have your webhook handler verify the sender, then call `route_inbound(session,
InboundMessage(...))` and `record_delivery(...)`. Use `mask_contact` anywhere a number is shown, and never log a key.
`ziira/plugins/messaging/providers.py: FakeChat` (a development-only conversational channel named `chat`) is the smallest example, and the one the tests use.
