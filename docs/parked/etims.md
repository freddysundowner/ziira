# eTIMS (parked)

**Status: parked, not on the to-do list.** The decision (with the owner) is to start trading with taxes entered by hand
(each product's tax code and VAT rate) and to build eTIMS later, **as an installable plugin**, once the arrangements with
KRA are settled. Nothing in the core waits for it. Take this file out of `parked/` when work on it starts.

## What the plugin will be

`ziira/plugins/etims`, installed and removed per business like any plugin (`ziira install etims`, `ziira enable <tenant>
etims`). A business without it behaves exactly as today. It keeps its own tables (`plg_etims`): the status of each document
(pending, submitted, failed), the KRA invoice number, signature and QR data, and what was last sent. Sales and invoices do
not change to carry any of this.

* **Listens** to `sale.posted`, `sale.returned` and `invoice.issued` / `invoice.cancelled`, and queues a submission with
  `@job` (retry with growing delays; failures to the exceptions inbox via `flag_for_review`).
* **Offline sales** are queued and submitted on reconnection, within the period the eTIMS rules allow (spec section 11).
* **Credit notes** for returns and for cancelled invoices.
* **Purchases:** pull the business's supplier invoices from eTIMS and match them to supplier bills (`purchasing`'s
  `supplier_bill.etims_ref` exists for the link); mark bills that have no eTIMS invoice.
* **Credentials** (the business's KRA PIN, branch and device details, keys): `store_credential(provider="etims")` (the
  provider name is already allowed), set up through an endpoint like the messaging channels.
* **Backlog:** everything sold before the plugin was installed is submitted in order when it is switched on, nothing numbered
  twice. This is why no "eTIMS status" column was added to sales: the plugin's own table is the status.

## What already exists in the core for it

| Need | Where |
|---|---|
| Tax type per tax code, item class per product | `products.tax_code.etims_tax_type`, `products.product.etims_item_class` |
| KRA PINs | `kernel.company.kra_pin`, `crm.customer.kra_pin`, `purchasing.supplier.kra_pin` (validated) |
| Link from a supplier bill to its eTIMS invoice | `purchasing.supplier_bill.etims_ref` |
| Events to listen to | `sale.posted`, `sale.returned`, `invoice.issued`, `invoice.cancelled` (payloads documented in POS) |
| Background work and retry | `@job` / `enqueue`, `ziira worker` |
| Encrypted credentials | `store_credential` / `read_credential` |
| Anything a person must look at | `flag_for_review` (the exceptions inbox) |
| Receipt and invoice output (KRA signature, QR code) | the `pos.receipt_extras` socket (`ReceiptExtra`, in `pos/public.py`) |

## Still to add when the work starts

* A **validation hook** before a sale posts, only if KRA requires signing before the sale completes (otherwise the plugin
  signs after commit and the receipt shows it once signed).
* Read access to the fields above through each module's `public.py` (products' eTIMS fields are not exposed yet).
* The plugin itself, its migration, its tests against KRA's sandbox, and the **KRA integrator certification** (a process
  with KRA that can take weeks; start it early when the time comes).

## Not decided

How the business is onboarded with KRA, whether sales are signed online at the till or after the fact, and who pays for the
certification. Settle these with KRA before designing the plugin in detail (spec sections 11 and 21, phase 5).
