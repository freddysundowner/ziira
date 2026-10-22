# Pharmacy or chemist pack (`pack_pharmacy`)

An industry pack: data only (`ziira/plugins/pack_pharmacy`). It makes a pharmacy, chemist or drug shop ready to trade on day one: a catalogue to
edit, stock tracked by batch and expiry date, a reference note at the till, expiry alerts, supplier templates and a short first-run checklist.

**What Ziira is not.** Ziira is **not a pharmacy management system or a medical record system**. It holds no patient records, no prescriptions,
no dosing or medical advice, and no clinical content anywhere (the example products carry names, strengths and pack sizes only). A pharmacy must
follow its own regulator's rules for dispensing, records, controlled items and storage; nothing here is advice on what those are. The reference
note at the till is a short text the business chooses to keep (a slip number); the cashier must not type medical details.

## What it sets up
* **Sign-up.** "Pharmacy or chemist" is offered after the usual choices when a business signs up for the Retail or Distribution edition
  (`GET /api/v1/industries?edition=retail`); the pack switches on Products, Inventory, Purchasing, Point of Sale and Customers with it. The
  pack can also be switched on later in Add-ons.
* **Catalogue** (`data/products.toml`): five categories (prescription-only medicines, over-the-counter medicines, supplements and vitamins, baby
  and personal care, medical devices and consumables); units of measure `TABLET`, `CAPSULE`, `STRIP`, `BOX`, `BOTTLE`, `SACHET`, `TUBE` (a unit the business
  already has is left alone); 27 **example products** (named "... (example)", SKUs `PHX-...`, no prices) with generic name, strength, form, storage,
  prescription yes/no and controlled yes/no filled in, a reorder level, and **batch tracking on** (everything with an expiry date). Two examples are marked
  controlled so the reference prompt can be tried. Edit them, hide the ones you do not stock; switching the pack off offers to hide the untouched ones.
* **Product fields** (`data/custom_fields.toml`, Settings > Custom fields): generic name, strength, form, manufacturer, prescription required,
  controlled item, storage; and on customers "Agreed to refill reminders".
* **Pack units.** Each example records the other units it comes in with their factor to the base unit (a strip of 10, a box of 100 tablets;
  `products.product_uom`). **Gap:** no screen sells or receives in these units yet; the till sells the base unit. A shop that sells both a strip and a
  tablet today keeps two products.
* **Stock control (Inventory, no new code needed).** A batch-tracked product is received with a batch number and expiry date (Purchasing > Receive,
  Stock > Opening stock, or the Data Import "opening stock" file); the till takes stock **first expiry, first out** by itself (`pick_first_expiry_first_out`),
  without the cashier choosing a batch. Added with this pack: a sale that draws on a batch **already past its expiry date** still posts (it has
  happened) and is **put in the exceptions inbox** (`expired_stock_sold`, high), and Home shows an **Expiring soon** box
  (`GET /api/v1/inventory/expiring?days=90`, batches with stock on hand, earliest first).
* **Intelligence** (`data/intel.toml`; limits are only set for checks the business has not tuned): `inventory.batch_expiring` warns 90 days ahead,
  urgent at 30; `inventory.batch_expired` (expired stock still on the books); `inventory.slow_stock`; `inventory.negative_stock` and `inventory.low_stock` (already
  on); price changes through `purchasing.supplier_price_rise` and `purchasing.margin_squeeze` (5%); and the new **`pos.reference_missing`**.
* **Reference note at the till.** Company setting `sale_reference_prompt` (Settings > General > "Ask for a reference at the till"): `off` (default), `ask`
  (the cashier may skip) or `require` (the line cannot be sold without a note). It applies to products whose custom field `prescription_required`
  or `controlled` is yes (`ziira/modules/pos/services/catalog.py: REFERENCE_FIELDS`); the catalogue says so per product (`reference_prompt`), the till opens
  the line to ask when the product is added, and the note (up to 120 characters) is stored on the sale line (`pos.sale_line.reference`) and sent with
  an offline sale. The check **`pos.reference_missing`** lists posted sales with a flagged item and no note (silent while the setting is `off`; urgent when one
  cashier has `high_after` of them). `require` is enforced at the till; a sale that arrives from an offline till without a note is accepted and shows up in the check.
* **Purchasing**: three supplier templates ("Example: ...", with payment terms, no contact or bank details) the business renames; reorder levels on the
  products. Switching the pack off offers to put untouched templates on hold.
* **Messages** (`ziira/kernel/message_templates.json`): `refill_reminder` and `order_ready`, English and Swahili. The refill wording never names a
  medicine. **Gap:** nothing sends a refill reminder automatically yet. Send them only to customers whose "Agreed to refill reminders" is yes; the kernel
  already skips anyone on the do-not-contact list.
* **First steps on Home** (`data/checklist.toml`, shown after the edition's own, 7 steps): review the examples and set prices; rename the suppliers; enter
  opening stock with batches and expiry dates; set reorder levels; choose the reference setting; open a till and make a test sale; choose how to hear about
  expiring stock. Packs can now add steps to Home this way (`industry.pack_steps`; `GET /api/v1/edition` returns them after the edition's own).
* **Home and menu** (`frontend/src/sdk/kindProfile.ts`, `shell/homeProfiles.ts`): kind `pharmacy` shows Sales today, Expiring soon, Low stock and Things to look
  at; the menu opens Sell and Stock first and keeps the till.

## Privacy
Customers are kept as in `docs/privacy.md`. The pack asks for nothing beyond what any shop keeps; the optional customer name on a sale and the reference
note are the business's own choice. Retention and erasure follow the company settings. Do not record diagnoses, conditions or treatments in notes or fields.

## Sample data
**Not built.** Stock movements and sales are immutable, so a "week of trading" cannot be removed again. The removable part is the example catalogue
(untouched products are hidden when the pack is switched off). To try batches, receive a few lines with batch numbers and dates, sell, and watch Home.

## What it does NOT do
No prescription or dispensing workflow, no patient records or medication histories, no drug-interaction or allergy checks, no regulator reporting or
controlled-drug registers, no automatic refill reminders, no selling by strip or box from a tablet balance (see pack units), no supplier price lists.
