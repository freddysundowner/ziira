# eTIMS (plugin skeleton)

**Status: skeleton.** The manifest, the status table (`plg_etims.submission`) and the contract (`public.py`) exist so the
shape is settled; nothing is sent to anyone and nothing listens to documents. The design, what the core already provides for
it and what is undecided (arrangements with the authority, whether sales are signed at the till or afterwards, the
integrator certification) are in `docs/parked/etims.md`.

Why a plugin: Kenya's eTIMS is a country-specific integration, so it does not belong in the core (rule 15). The core only
carries neutral columns it fills: `tax_code.authority_code`, `product.authority_item_class`, `supplier_bill.authority_ref`.

To build it: implement `AuthorityGateway`, subscribe to the sale and invoice events in an `events.py`, queue submissions with
`@job`, and record each outcome in `plg_etims.submission`. Test against the authority's sandbox before any live use.
