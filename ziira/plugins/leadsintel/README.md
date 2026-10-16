# WhatsApp through Lead Intel (plugin)

Provides the `whatsapp` channel (provider `leadsintel`) so alerts, briefs, approvals and customer reminders can go out by
WhatsApp, and replies can come back. It is a real plugin: when it is not enabled for a business, WhatsApp does not exist for
that business anywhere (settings, preferences, screens, templates). Architecture, the Lead Intel specifics and **what is not
verified**: `docs/channels.md`.

* `client.py` the HTTP client (platform key header, error shape); `providers.py` the channel (it declares templates, reply
  buttons, replies and the 24-hour window); `unverified.py` every request Lead Intel has not documented (template creation and
  status), all marked `# UNVERIFIED`; `services/setup.py` connecting a number; `services/webhook.py` the signed inbound
  endpoint; `api/routes.py` the endpoints.
* Keys: `store_credential` (platform key and webhook secret, encrypted); never returned or logged.
* Needs `ZIIRA_PUBLIC_BASE_URL` to be a public https address (Lead Intel posts incoming messages there).
* **Never run against the real service.** Test with a Lead Intel account and a test number before relying on it.
