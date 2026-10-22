# Pack Education: tutor, school or training centre (`pack_education`)

An industry pack (`docs/industry-packs.md`): data only, on top of Bookings (classes) and Memberships (fees). It needs Products, Memberships and Bookings;
Intelligence, Customers and Point of Sale (invoices) make it more useful. Switch it on at sign-up ("What kind of service business are you?") or in Add-ons;
`ziira apply-packs <tenant>` seeds it again and only adds what is missing. It names no country, currency or tax rate.

## How a tutoring centre or school is modelled

| In real life | In Ziira |
|---|---|
| A learner | A **customer** with a member profile (grade, guardian, who may collect them, date of birth and emergency contact are on the profile) |
| The parent or guardian who pays | A customer who is the **payer of a household** (`Memberships > Households`). The learner is put in the household. |
| Term fees, paid once or in instalments | A **fee plan** (a fixed-term plan: one period of a quarter, or 2 or 3 monthly instalments). Enrol the learner on it with the term's start and end date: the invoices go to the parent, the learner stays the member. |
| Sibling discount | A cheaper fee plan for the second and later child (`TERM-SIB`, `TERM3-SIB`, example fees). Put each child on the plan that fits. |
| A class with a roster | A **class** in Bookings (a service of kind "class" with a capacity). Put it in the timetable for every week of the term; book each learner on it; a full class has a waitlist. |
| Attendance | Mark each learner attended or absent on the class (Bookings). |
| A make-up session | The "Make-up session" class (capacity 6): book the learner on it. |
| A tutor paid for hours | Sessions are on the teacher in Bookings; Memberships' trainer rates and earnings (`GET /memberships/trainers/earnings`) read the finished sessions. Nothing is paid from here. |
| A report or result | A file on the learner's profile, kind "Report or result" (or "Certificate"), staff-only until you mark it shareable (`docs/files.md`). |
| Fees arrears | Memberships' money-owed list (`GET /memberships/arrears`), by payer. |
| A one-off or custom term | A **recurring invoice** with the parent as customer and the learner in "for": `POST /memberships/recurring-invoices {customer_id: <parent>, for_customer_id: <learner>, for_label: "Term 2"}`. It appears in the same arrears list. |

### Running a term
1. Before the term: put each class in the timetable (weekly) and book the learners on it. Check the class sizes.
2. Enrol each learner on a fee plan with the **start date** of the term and the **end date** of the term. The first invoice (or the whole term) is made at once; later instalments by themselves.
3. Each class: mark attendance. A learner absent three times in four weeks shows up for you to call.
4. Two weeks before the end of the term: Intelligence tells you which families still owe fees on terms about to end.
5. At the end: attach the reports, mark the ones to share, enrol for the next term.

## What it sets up
* **Service items** (no prices): tuition fees, registration fee, books and materials, exam fee, one-to-one lesson, make-up session, and one per class below.
* **Fee plans** (every fee is an EXAMPLE and says so until you change it): term fees paid once, in 3 instalments, in 2 instalments, sibling versions of the first two,
  and monthly tuition with no fixed term. **Bundles**: 5 and 10 one-to-one lessons, an 8-session revision course (with expiry).
* **Classes** (example prices, capacity as a starting point): Mathematics, English, Science, Language, Computer skills, Art and music, Exam revision, Holiday
  programme, Make-up session (all groups, teacher and room held together) and the One-to-one lesson.
* **Teachers and rooms**: Teacher 1 and 2, Classroom 1 and 2, Monday to Friday (and Saturday morning for the first). Rename them.
* **Policies**: late-fee messages at 7, 14 and 30 days, no "we miss you" messages, nothing held back for unpaid fees, reminders 14 days before the next instalment, a cancellation window of 24 hours.
* **Terms**: placeholder enrolment terms and guardian consent (it says so; it is not legal advice).
* **Fields**: on the learner's profile: grade or class, school, parent or guardian and phone, relation, who may collect the learner, what the learner wants to achieve;
  on the enrolment: class or group, main teacher. Date of birth, emergency contact and notes are on the profile already (optional). **No health information.**
* **Check limits** for Intelligence, below.
* **Wording** (English and Swahili, with the platform's templates): `school_fees_due`, `school_absent`, `school_term_end`, plus the existing `class_booked`, `class_cancelled`,
  `membership_payment_late` and `membership_renewal` (see "Messages" for what is sent by itself).

## Intelligence
Silent when all is well. Limits are the business's to change (Settings > Intelligence).
* **Fees overdue** (`memberships.payment_late`): families with an invoice 7 days late or more, urgent at 30.
* **Terms ending with fees unpaid** (`memberships.term_ending_unpaid`, new): terms (an enrolment or a recurring invoice with an end date) ending in the next 14 days while an invoice on them is open.
* **Classes with few places taken** (`bookings.class_underfilled`, new): a class in the next 3 days with less than 40% of its places taken (classes under 4 places are ignored). New for every business that runs classes.
* **People often absent** (`bookings.class_absences`, new): absent from 3 sessions or more in 28 days, urgent at 6.

## First-run checklist (shown on the Bookings screens until done; six steps that tick themselves)
1. Set your own fees: class prices (Services) and the fee plans (Memberships, Plans and packs).
2. Name your teachers and classrooms.
3. Link each class to its service item.
4. Put your first class in the timetable.
5. Take attendance for your first class.
6. Switch on the booking page, if families book trial lessons or make-ups themselves.

## Sample data
`.venv/bin/python scripts/seed_demo_school.py` creates the development business `demo-school` ("Bright Tutors", login `owner@demo-school.test`) with the pack on and a believable
year-in-two-terms: families with one or two children, Term 1 (finished, mostly paid) and Term 2 (half done), a weekly timetable with rosters, attendance, a full class with a
waitlist, an under-filled class, a learner often absent, a family with fees late, a term about to end with fees unpaid, reports attached to two learners. `--reset --confirm demo-school` deletes
the business and starts again. Development only.

## Privacy: learners may be children
* Learners, guardians and their notes are customers and profile data: found, exported and erased through the personal-data tools (`docs/privacy.md`, the `memberships`, `bookings` and `crm` providers).
  Invoices and attendance that must be kept are kept; names and contact details are removed.
* Retention periods and what must be kept are company settings (Settings > Privacy), never fixed here. Reports and photos are private files with a staff-only default; marking a file shareable is a person's choice and is logged;
  every opening of a full-size file is logged (`files.audit`).
* The pack adds **no** health, special-needs, religion or ethnicity fields. The enrolment terms placeholder asks for guardian consent and mentions photographs; have the wording checked for your country.
* Parent and guardian phone numbers are only used for fees, attendance and class messages; a person who asked not to be contacted is never messaged.

## Messages
Late-fee reminders and renewal reminders go by themselves (Memberships policies). A cancelled class tells the families booked on it (`class_cancelled`). The wording `school_fees_due`,
`school_absent` and `school_term_end` is shipped and approved with the platform's other templates, but **nothing sends them by itself yet** (see "What it does NOT do").

## What it does NOT do
Exam boards and curricula, timetable clash solving across a whole school, grades and gradebooks, a parent app or portal, boarding, school transport, a canteen, card-on-file charging,
sending the absent or end-of-term messages automatically, a "learners absent" box on Home, health or special-needs records, bursaries, or a legal text.
Term dates are the enrolment's start and end dates, not a separate calendar; sibling discounts are separate fee plans, not a rule. Prices, tax and currency are yours.
Switching the pack off keeps everything; "remove untouched" retires fee plans and bundles nobody changed or used and removes classes, teachers and rooms nobody used.
