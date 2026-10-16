# billing_stripe

A payment gateway for **subscription payments**: lets a business pay Ziira's invoices by itself with card payments through Stripe Checkout.
It implements `kernel.payment_gateway` and is found at platform level (`platform_scope = true`): a business never switches it on.
The operator enters its keys in Super Admin > Billing > Payment methods.

Everything about the flow, the settings, what is unverified in the provider's documentation and the live-test checklist is in
`docs/subscription-payments.md`. Tests are in `tests/test_subscription_payments.py` (mock transport only; no real service is called).
