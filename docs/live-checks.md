# Live-service checks

Ziira's M-Pesa (Daraja), SMS and email code was written from the vendors' public documentation and has **never been
run against the real services**. `scripts/live_check.py` is a careful harness you run by hand, with **sandbox**
credentials, to find out. It calls the app's own provider classes (`ziira.modules.payments.providers`,
`ziira.plugins.messaging.providers`), so a PASS means the code production runs works. Nothing it prints contains a
secret (headers and secret fields are replaced with `***hidden***`), and it never writes credentials anywhere.

Credentials are environment variables you set in your shell for the run (do not put them in `.env` files that get
committed; `.env` is git-ignored, but a shell `export` that is gone when you close the terminal is safest).

```bash
set -a; . ./.env; set +a          # the app's own settings (daraja-callback needs the same ZIIRA_SECRET_KEY as the API)
.venv/bin/python scripts/live_check.py <check> --dry-run     # first: print the requests, send nothing
.venv/bin/python scripts/live_check.py <check> ...           # then for real
```

`--dry-run` feeds the provider code a made-up reply shaped like the vendor's documented one and prints the requests it
would send. It proves the request format only, never that the vendor accepts it. The harness refuses to run when
`ZIIRA_ENV=production` unless you pass `--i-know`. Daraja is always called in its **sandbox**.

## 1. Daraja (M-Pesa)

**Get sandbox credentials**

1. Sign up at Safaricom's developer portal (developer.safaricom.co.ke) and sign in.
2. My Apps, Add a new app, tick the **Lipa Na M-Pesa Sandbox** product (add the others you will test later, such as C2B).
   Open the app: copy the **Consumer Key** and **Consumer Secret**.
3. In the portal's API simulator for *M-Pesa Express* (STK push) copy the sandbox **shortcode** and **passkey** it shows
   (the sandbox's shared test values). Use its **test phone number** for `--phone`.
4. The sandbox needs a callback address it can reach over HTTPS. For a check from your laptop use a tunnel to
   port 8000 (any tunnelling tool), and set `ZIIRA_PUBLIC_BASE_URL` to the tunnel's address when starting the API.

```bash
export ZIIRA_LIVE_DARAJA_CONSUMER_KEY=...  ZIIRA_LIVE_DARAJA_CONSUMER_SECRET=...
export ZIIRA_LIVE_DARAJA_SHORTCODE=...     ZIIRA_LIVE_DARAJA_PASSKEY=...
export ZIIRA_LIVE_DARAJA_CALLBACK_URL=https://<your-tunnel>/api/v1/payments/callbacks/stk/test   # any HTTPS address
# optional: ZIIRA_LIVE_DARAJA_TILL_TYPE=till   (default paybill)
.venv/bin/python scripts/live_check.py daraja --dry-run
.venv/bin/python scripts/live_check.py daraja                # --phone 254708374149 --amount 1 --polls 6
```

**A pass** shows three exchanges: the OAuth token (200), the STK push (`ResponseCode "0"`, a `CheckoutRequestID`),
the query (a `ResultCode`, or a "being processed" answer, which counts as pending), then `PASS`. In the sandbox no real
phone gets a prompt; the simulator is where you see and answer it.

**On a failure**

| You see | Do |
|---|---|
| "Safaricom refused the credentials" / 400 or 401 on the token | Re-copy the key and secret of the *sandbox* app (watch for a trailing space). |
| Push refused with an `errorMessage` | Read it. Usual causes: shortcode and passkey that do not belong together, an invalid or non-HTTPS callback URL, a bad phone number. |
| HTTP 500 with a message about wrong credentials or "being processed" | See doubts D1 and D2 below, and tell us exactly what came back. |
| Connection errors or timeouts | Sandbox outages are common; retry later, and check the network. |

**Callback self-test.** Start a prompt in the app (or `POST /api/v1/payments/intents`) against a sandbox account, wait for
the worker to send it (`ziira worker --once`), then take the intent's id and its checkout id (the intent shows the
provider request id) and run, with the API running and `ZIIRA_SECRET_KEY` the same in both places:

```bash
.venv/bin/python scripts/live_check.py daraja-callback --api-url http://localhost:8000 \
    --tenant-id <tenant uuid> --intent-id <intent uuid> --checkout-id ws_CO_... [--dry-run]
# optional: ZIIRA_LIVE_API_TOKEN=<a sign-in token>  (otherwise the development header X-Tenant-ID is used to read the intent)
```

It builds the same signed address the app gives Safaricom, posts a sample success callback with a fresh made-up
receipt number, and reads the intent back. **A pass** is status 200 and an intent with status `succeeded` and that
receipt. A 404 means a wrong signature or tenant (different `ZIIRA_SECRET_KEY`, wrong ids). The intent must still be
pending (a callback is applied once). Do this against a development tenant: the sample creates a real transaction there.

Beyond this script, the go-live item also needs C2B URL registration, validation and confirmation callbacks tried from
the portal; this harness does not cover C2B.

## 2. SMS (BlessedTexts)

1. Create an account with BlessedTexts, buy a little credit, and get an **API key** from its dashboard.
2. Register a **sender id** and wait for its approval (the provider decides how long this takes).

```bash
export ZIIRA_LIVE_SMS_API_KEY=...  ZIIRA_LIVE_SMS_SENDER_ID=...
.venv/bin/python scripts/live_check.py sms --to 2547XXXXXXXX --dry-run
.venv/bin/python scripts/live_check.py sms --to 2547XXXXXXXX --message "test"       # a number you control
```

**A pass**: the raw reply (printed) is a list whose first entry has `status_code "1000"`, the harness prints `PASS`, and
**the text arrives on your phone** (always confirm that). **Failures**: print the raw reply and note each different
`status_code` and `status_desc` you get for a wrong key, an unapproved sender id and an empty balance (deliberately
try each once): the app only knows `1000` means success; the rest are treated as permanent refusals. Add what you learn
to `docs/notifications.md` and to the go-live item.

## 3. Email (SMTP, Brevo, Resend, SendGrid)

Use the provider the first customer will use. For each, the **sender must be verified** at the provider (a single sender
address, or a domain with SPF/DKIM) before it will send.

```bash
export ZIIRA_LIVE_EMAIL_FROM_ADDRESS=verified@your-domain  # optional ZIIRA_LIVE_EMAIL_FROM_NAME
# brevo | resend | sendgrid:
export ZIIRA_LIVE_EMAIL_API_KEY=...
.venv/bin/python scripts/live_check.py email --provider brevo --to you@example.com --dry-run
.venv/bin/python scripts/live_check.py email --provider brevo --to you@example.com
# smtp:  ZIIRA_LIVE_SMTP_HOST, ZIIRA_LIVE_SMTP_USERNAME, ZIIRA_LIVE_SMTP_PASSWORD, optional ZIIRA_LIVE_SMTP_PORT (587; 465 = TLS)
.venv/bin/python scripts/live_check.py email --provider smtp --to you@example.com
```

**A pass**: the provider's reply (Brevo 201 with a `messageId`; Resend 200 with an `id`; SendGrid 202; SMTP no
exception) and the mail arrives (check spam; look at the headers for SPF and DKIM `pass`). **Failures**: a bad key,
an unverified sender and a bad recipient should each be tried once on purpose so you see the provider's real words;
compare with doubts D5 and D6. With `--dry-run`, SMTP prints the message and the login step (password hidden) only.

## 4. AI provider (Anthropic Messages API)

The assistant's provider code (`ziira/plugins/ai_anthropic/provider.py`) was written from Anthropic's public documentation and has
not been run against the live API. The check sends one harmless prompt, then a tool-use round trip with a made-up `echo` tool (the
mapping most likely to need a fix), through the app's own provider class. It costs a few dozen tokens.

```bash
export ZIIRA_LIVE_AI_API_KEY=...            # a key you can revoke; optional: ZIIRA_LIVE_AI_MODEL, ZIIRA_LIVE_AI_BASE_URL
.venv/bin/python scripts/live_check.py ai --dry-run     # prints the requests (key hidden); the key is not needed
.venv/bin/python scripts/live_check.py ai               # add --no-tool for the plain prompt only
```

**A pass**: step 1 gets text back with token counts; step 2 shows a `tool_use` block for `echo` with `{"text": "ping"}` and then a
final text after the `tool_result`. **On a failure** read the provider's own words: a 401 is the key, a 404 or "model" is the model
id (default `claude-sonnet-5-5`; set `ZIIRA_LIVE_AI_MODEL`), a 400 about a field means the request shape needs a change in
`build_request`. Then see `docs/ai.md` section 11 for what else is unverified.

## 4b. The platform's WhatsApp bot (Lead Intel)

`ziira/plugins/leadsintel_platform/provider.py` was written from the public page https://leadsintel.net/developers.html and has not been run against the real service (what is not confirmed by the page is marked `# UNVERIFIED` and listed in `docs/ai.md` section 15).
The check is read only: it tests your platform key with a harmless read, optionally looks a number up, and proves the signature code accepts a delivery signed the documented way and refuses a tampered one. It never connects, changes or sends anything, and the key is read from the environment only.

```bash
.venv/bin/python scripts/live_check.py chat --dry-run                 # prints the requests (key hidden); no key needed
export ZIIRA_LIVE_LEADSINTEL_KEY=...                                  # your Lead Intel platform key
.venv/bin/python scripts/live_check.py chat [--lookup +2547XXXXXXXX]
```

**A pass**: step 1 shows the key accepted (a 404 for the request that cannot exist is the expected answer); the lookup (if given) says what Lead Intel knows; step 3 reads one signed message and refuses the tampered one. **On a failure**: a 401 is the key; anything else, read Lead Intel's own words.
The rest (connecting a number, receiving and answering a message, the 24-hour window) is done by hand in Super Admin > WhatsApp bot following "Going live" in `docs/ai.md` section 15.

## 5. Go-live gate

Tick these in `docs/go-live-checklist.md`, with the date and who did it, only when the real result is in front of you:

- **Safaricom Daraja**: `daraja` PASS; `daraja-callback` PASS against a development tenant; C2B registered and its
  confirmation received from the portal; doubts D1 to D3 answered by what the sandbox really returned (and the code fixed
  if they were real). Production needs the business's own shortcode and a production app: repeat with those by hand
  (the harness stays sandbox-only on purpose).
- **BlessedTexts SMS**: `sms` PASS with the live key and approved sender id; the text arrived; the codes for bad key, bad
  sender and no credit written down (doubt D4).
- **Email**: `email` PASS for the provider the customer uses; the message arrived with SPF/DKIM passing; error replies
  seen (D5, D6).
- Also: the registration email (`ZIIRA_PLATFORM_EMAIL_*`) item, since it uses the same email providers.
- **AI provider** (only if the assistant will be offered): `ai` PASS with the live key; the provider's no-training and retention
  terms in place (`docs/ai.md` section 9).

## 6. Doubts found when reading the providers (nothing was changed in the code for these)

These come from reviewing the code against the vendors' public documentation from memory. Each is a thing to look at
in the real reply, not a known bug.

- **D1 (Daraja, pending query).** `query_stk` raises as "unavailable" for any HTTP status of 500 or more before it looks
  at the body. As far as we remember, Daraja answers a query for a prompt that is still being processed with an error
  body (`errorCode "500.001.1001"`, "The transaction is being processed") and **HTTP 500**. If so, a pending prompt is
  seen as an outage and retried instead of read as pending (the code does handle the same text when the status is not 5xx).
  Watch the status and body of the first queries.
- **D2 (Daraja, push errors).** The same 500 habit may apply to `stk_push`: a wrong shortcode/passkey or credentials can come
  back as HTTP 500 with an `errorMessage`, which the code retries rather than treating as a permanent refusal.
- **D3 (Daraja, amounts).** `int(request.amount)` truncates, so 10.50 is sent as 10 and the prompt differs from the
  invoice. Daraja takes whole amounts as far as we know; the caller should refuse fractions, not truncate. Also confirm
  whether `PartyB` and `BusinessShortCode` are used as the code assumes for a buy-goods till (`CustomerBuyGoodsOnline`:
  shortcode is the store number, `PartyB` the till).
- **D4 (BlessedTexts).** Endpoint path, field names (`api_key`, `sender_id`, `phone`, `message`), the phone format
  (with or without `+`), the reply shape (a list, `status_code "1000"`) and the error codes cannot be confirmed from
  memory. The first real reply settles all of them.
- **D5 (Resend and SendGrid, 403).** Both code paths map HTTP 401 and 403 to "refused the API key". As far as we remember,
  both also answer **403** for an unverified sender or domain, so the message would blame the key for a sender
  problem. Check the real reply and split the cases by body.
- **D6 (SMTP).** Only authentication, recipient and sender refusals are classed as permanent. Other refusals (for example
  a 5xx rejection of the message content, `SMTPDataError`) escape as exceptions and are retried. Check what your server
  does with a bad recipient domain and a message flagged as spam.
- **D7 (Africa's Talking, not run by this harness).** Built but unused; its sandbox needs the username `sandbox`, and a
  success is HTTP 201. The code handles that by reading the body, not the status. Not covered by a check until a customer uses it.
