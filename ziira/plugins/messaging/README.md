# Messaging channels (plugin)

Sends the messages other units ask for (`send_notification`): **email** through any SMTP server, **SMS** through
Africa's Talking, **WhatsApp** through the WhatsApp Cloud API. The kernel owns the queue, the record of what was sent and
the list of people who asked not to be contacted; this plugin only knows how to deliver one message through a gateway.

> The SMS and WhatsApp request formats were written from the gateways' public documentation and **have not been run
> against the real services**. Try each with its sandbox or a test number (`POST /api/v1/notifications/test`) before
> relying on it.

Set up a channel per business (permission `settings.manage`):

```
PUT /api/v1/notifications/channels/sms
{"company_id": "...", "provider": "africastalking", "secret": {"api_key": "..."},
 "config": {"username": "mybusiness", "sender_id": "MYSHOP"}}
```

| Channel | Provider | Secret | Config |
|---|---|---|---|
| email | `smtp` | host, port, username, password | from_address, from_name, starttls |
| sms | `africastalking` | api_key | username, sender_id, sandbox |
| whatsapp | `whatsapp_cloud` | access_token | phone_number_id, template, language, api_version |
| any | `fake` | any (development only) | |

A failure that may pass (the gateway is unreachable, a server error) is retried with growing delays up to five times; one
that will not (wrong keys, a refused number) fails at once and is put in the exceptions inbox. Adding another provider
(another SMS aggregator, a mail API) is a class implementing `NotificationChannel` with `@provides`.
