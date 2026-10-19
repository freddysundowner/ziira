# Pack Fitness: gym, studio or personal trainer

`ziira/plugins/pack_fitness` is an industry pack (`docs/industry-packs.md`): data only. It needs Products and Memberships; Intelligence, Bookings
(classes and personal-training sessions) and Point of Sale (invoices, retail) make it more useful. Switch it on at sign-up ("What kind of service
business are you?") or in Add-ons; `ziira apply-packs <tenant>` seeds it again and only adds what is missing. How everything below works:
`docs/memberships.md`, "Gyms and studios".

## What it sets up
* **Service items** (no prices): gym membership, joining fee, day or week pass, visit pack, class or class pack, personal training session, locker or
  towel rental, gift voucher.
* **Plans** (every fee is an EXAMPLE, marked "example price" until you change it): Monthly (joining fee, one guest pass, 30 days of freeze a year), 12 month
  contract (minimum term, 30 days' notice, early-exit fee), Annual paid once a year, Off-peak (weekdays 10:00 to 16:00), Classes only (eight classes a
  month), Day pass, Week pass, Free trial (3 days).
* **Packs**: 10 visits, 10 classes, 5 and 10 personal-training sessions (with expiry).
* **Policies**: 7 grace days for late payers, late-payment messages at 1, 7 and 14 days, "we miss you" after 3 weeks, terms required before entry.
* **Terms**: placeholder wording to replace with your own (it says so; it is not legal advice).
* **Fields**: main goal, experience, usual time of day on the member; preferred trainer on the membership. No health data.
* **Check limits** for Intelligence: members gone quiet, payments late, refused entries overridden.
* Message wording in English and Swahili lives with the platform's templates (late payment, on hold, we miss you, birthday, trial follow-up, renewal).

## First-run checklist (also shown on the Memberships page until done)
1. Set your own prices on the plans (the "example price" mark disappears).
2. Check each plan is linked to a service item (Plans and packs).
3. Write your terms (Memberships, Plans and packs, Terms) and who must accept them.
4. Review the policies (grace days, messages, quiet hours).
5. Add your first member (photo from the phone, card number, emergency contact).
6. Try the check-in: type a name, scan the number, and print or save the member's QR (`ZM:<member number>`).
7. If you have a door or turnstile: create an API key with the permission "Check members in" and give it to the installer (docs/memberships.md, access-decision API).

## Sample data
`.venv/bin/python scripts/seed_demo_gym.py` creates the development business `demo-gym` ("Peak Gym", login `owner@demo-gym.test`) with the pack on and a
believable month: 40-odd members on every kind of plan, a household and a company account, late payers, a hold for unpaid fees, an injury freeze, a
cancellation with its reason, packs, a trainer, a voucher, lockers, a guest and a month of check-ins with morning and evening peaks. `--reset --confirm demo-gym`
starts again. Development only.

## What it does NOT do
Hardware drivers, card-on-file charging, a member app, medical records or health questionnaires, nutrition plans, equipment maintenance, a legal text.
Prices, tax and currency are yours. Switching the pack off keeps everything; "remove untouched" retires plans and packs nobody changed or used.
