# Parked: industry editions (hotel, restaurant, services)

Parked on 2026-10-15 by the owner: finish the current work first, then revisit.

## Question
Can Ziira run a hotel, a service business, or any other kind of business?

## Where we are
Works for any business today: accounting, people and payroll, customers and credit, purchasing, approvals, payments and
matching, Intelligence (cash, payroll, supplier and control checks), quotations and invoices.

Built for retail and distribution only: the till and stock model (items sold from a shelf). Not tested as a service-only till.

## What is missing
- **Hotel and lodging:** rooms and room types, reservations and availability calendar, check-in/out, guest folio that builds
  up over a stay, housekeeping status, rate plans and seasons, night audit.
- **Restaurant:** tables and orders, kitchen tickets, recipes and ingredient costing, tips, split bills.
- **Service businesses (salons, clinics, agencies, repairs):** appointments and staff scheduling, time and project billing,
  recurring invoices and retainers, job cards.

## How it would be added
Each industry is its own module plus an *edition* (see the Editions work): hospitality (rooms, bookings, folio posting to
Finance and the till), restaurant (tables, orders, kitchen screen on the POS), services (appointments, time billing,
recurring invoices, no stock). Each brings its own Intelligence checks (for example room revenue against cash, no-shows,
discounts by staff). No country in code (rule 15).

## Recommendation
Do not build all three at once. Pick the industry the next customers are in and build it end to end with tests. Services is
cheapest (reuses most); hotels are the largest. Next step when revisited: a short design and plan for the chosen industry.
