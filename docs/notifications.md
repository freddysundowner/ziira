# Messages to customers and suppliers

The kernel sends messages to people outside the system (a customer reminded about an invoice) so that no unit has to know
about gateways. A unit calls `send_notification(...)`; the kernel records the message in the caller's transaction and a
background job sends it through the business's channel for that medium.

```python
from ziira.sdk import send_notification
send_notification(session, company_id=co, channel="sms", recipient="0712345678",
                  body="Your invoice INV-1 is due.", ref_type="sales_invoice", ref_id=invoice.id,
                  dedupe_key=f"reminder:{invoice.id}:{today}:sms")
```

* **Channels** are email, SMS and WhatsApp. Each business sets up its own (`PUT /api/v1/notifications/channels/{channel}`,
  permission `settings.manage`): which provider, and the keys, which are stored encrypted and never shown again.
  `POST /api/v1/notifications/test` sends a test message.
* **Providers** come from the `messaging` plugin: `smtp` (email), `africastalking` (SMS), `whatsapp_cloud` (WhatsApp) and
  `fake` (development). To support another gateway, write a class implementing `NotificationChannel` and register it with
  `@provides("kernel.notification_channel")`. The SMS and WhatsApp formats were written from the gateways' documentation and
  have not been run against the real services: test each in the gateway's sandbox first.
* **Do not contact.** `POST /api/v1/notifications/opt-outs` (or a customer's `do-not-contact` in CRM) stops all messages, or
  those on one channel, to a person. Such a message is recorded as skipped and never sent.
* **Failures.** A failure that may pass (gateway unreachable, server error) is retried up to five times with growing delays;
  one that will not (wrong keys, a refused number) fails at once; either way the exceptions inbox is told. With no channel
  set up the message is skipped and flagged once.
* **Record.** `GET /api/v1/notifications` shows what was sent and what became of it (recipients masked). Messages cannot be
  edited or deleted.

## Recurring tasks

Work that must happen every so often is registered with `@periodic("unit.name", every_seconds=N)` in the unit's `jobs.py`.
`ziira worker` runs each for every business that has the unit enabled, at most once per interval (claimed in the database,
so several workers never run it twice). A task that fails is recorded, flagged, and tried again at its next interval.
