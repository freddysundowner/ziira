# leadsintel_platform

The platform's own chat bot through Lead Intel: the platform owner connects ONE WhatsApp number in Super Admin > WhatsApp bot,
and anyone who writes to it gets the same checked answers as the website assistant (about Ziira itself: what it is, plans and
prices, how to sign up). It implements `kernel.platform_chat_channel` and is found at platform level (`platform_scope = true`):
no business switches it on. It is separate from the per-business `leadsintel` plugin (that one is a notification channel for a
business's own customers and staff); both talk to the same Lead Intel API but share no data.

* `provider.py` Lead Intel (connect a number, read a signed delivery, send); `fake.py` the development provider
  (`ZIIRA_CHAT_FAKE=1`); `common.py` the signature check and delivery reading both use.
* The key and the webhook secret are stored encrypted by the platform (never in this plugin) and never returned or logged.
* Everything about the screen, the flow and what is **not verified** is in `docs/ai.md` section 15.
* Tests: `tests/test_chat_bot.py` (mock transport only; nothing reaches the real service).
