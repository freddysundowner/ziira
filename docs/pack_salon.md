# Salon, spa or barber pack (`pack_salon`)

An industry pack: data only (`ziira/plugins/pack_salon`). Switch it on at sign-up ("Salon, spa or barber") or in Add-ons. It needs Products and
feeds Appointments and Bookings (`bookings`), Intelligence and custom fields. See `docs/industry-packs.md` for how packs work and `docs/bookings.md`
for the unit.

## What it sets up
* **13 services** with usual durations, set-up/clean-up minutes and, where it matters, **processing time** (colour, highlights and relaxers leave the
  stylist free while the product sets), a deposit for long services, "needs a patch test", and "due again after N days" for the services people repeat.
  Every price is an **example** (marked "Example price" until you set your own).
* **Prices by staff level** (Senior stylist / Stylist for a cut) and a "Long hair" price for colour and braids.
* **Staff and room templates**: Stylist 1 (Senior), Stylist 2, Barber chair 1, Treatment room 1, Monday to Saturday 09:00-18:00, marked as templates.
* **Commission rules**: 30% on services, 40% for Senior staff, 10% on retail products (change or delete them in Staff pay).
* **Policy suggestions**: 24-hour cancellation window, late-cancel fee 50% and missed-appointment fee 100% of the price, rebooking invitation 3 hours after
  a visit, "due again" reminders, a patch test good for 180 days, a 30-minute window to confirm a freed class place.
* **Client card fields**: preferred stylist, allergies (a note), colour formula/notes, hair type, patch-test date (with an expiry warning on the booking),
  agrees to before/after photos. Photos and documents attach to the client card (Photos and files service).
* **Intelligence limits** for no-shows, late cancellations, unused time and idle gaps.
* **First-run checklist** on the Front desk (7 steps that tick themselves): set prices, name staff, link services to service items, choose the fee item,
  switch on the booking page, take a first booking, check out a first client.
* **Sample week** (Booking settings > Sample data): a few made-up clients and a week of visits so the screens are not empty. It bills nothing and can be removed.

## Edit first
1. Services offered: set your own prices (the badge disappears) and link each service to a service item in Products.
2. Staff and rooms: rename the templates, set each person's level and hours.
3. Booking settings: the item fees are billed under, deposit wording, your booking address.
4. Staff pay: the commission rules.

## What it does NOT do
No clinical or medical advice (the patch-test date is a date the business enters; how long it stays valid is the business's setting). No stock for
retail products (that is Inventory and Products). No online payment link for deposits (staff record a deposit paid; a gateway is not built). Tips are
recorded and tracked (kept apart from revenue) but not posted to the books. No hardware, no loyalty scheme (the voucher/points socket is
`bookings.checkout_tender`; Memberships owns the credit side).
