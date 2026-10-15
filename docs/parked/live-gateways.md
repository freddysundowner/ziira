# Live gateway testing: SMS, email and M-Pesa (parked)

**Status: parked, not on the to-do list.** Decision (with the owner): the request formats for the SMS gateway (BlessedTexts), the
email providers (SMTP, Brevo, Resend, SendGrid), Safaricom's Daraja (M-Pesa) and, later, the AI provider are written from public
documentation and have been tested only against mocks. Running them against the vendors' sandboxes and then live is **set aside until a
business needs the channel**; nothing else waits for it.

Until then:

- Nothing is sent unless a business turns a channel on (alerts and briefs default to the app only; reminders are off by default).
  Registration emails use the platform provider and need a working one before open registration (production refuses to start without it).
- Mobile-money collection by prompt (`pos`/`payments`) must not be offered to a business until the Daraja check has passed.
- Everything needed to resume is kept: `scripts/live_check.py` (dry-run works now), `docs/live-checks.md` (how to get sandbox credentials, run
  each check, read the result, the go-live gate), the provider doubts D4-D7 listed there (D1-D3 were fixed), and the go-live checklist items.

## To resume

1. Read `docs/live-checks.md`; get sandbox credentials for the channel the first business needs.
2. Run `scripts/live_check.py <daraja|sms|email|ai> ...` with `--dry-run` first, then for real; fix what the vendor's replies show.
3. Tick the matching lines in `docs/go-live-checklist.md` and move this file's relevant paragraph back into `docs/`.
