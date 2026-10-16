"""The Super Admin platform: plans, subscriptions, licences, billing and the subscribers directory
(docs/platform-admin.md).

Everything here lives in the master database and is reached only by platform staff (operators) or, for the business's
own plan and invoices, through `ziira.kernel.api.billing_routes`. Prices, limits, tax rates and schedules are rows the
vendor enters, never constants.
"""
