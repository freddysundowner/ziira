# Clinic or dental practice pack (`pack_clinic`)

An industry pack: data only (`ziira/plugins/pack_clinic`). **Appointments and billing only. Ziira holds no clinical records**: no diagnoses,
prescriptions, results, treatment notes or images of a medical kind. Administrative documents (a signed consent form, a referral letter) may be attached to
a client or an appointment; the screens say it is not a medical record system.

## What it sets up
* **8 appointment types** (new-patient and follow-up consultations, dental check-up, scale and polish, filling, extraction, physiotherapy session, review)
  with usual durations and example prices (marked as examples); "due again after 180 days" on check-ups so the recall list and reminders work; a deposit on
  fillings.
* **Practitioner and room templates** (Practitioner 1, Practitioner 2, Consulting room 1), Monday to Friday and Saturday morning.
* **Wording**: clinic reminder, due-again and rebooking messages in English and Swahili (`appointment_reminder_clinic`, `appointment_recall_clinic`,
  `appointment_rebook_clinic`); the reminder asks the patient to bring their insurer card.
* **Fields (administrative only)**: on the appointment "New or follow-up" and "Bill to" (patient, insurer or scheme, employer); on the client card insurer,
  member number, preferred practitioner, referred by, contact person.
* **Intelligence limits** for no-shows and unused time. **First-run checklist** (6 steps). Sample week as for the salon pack.

## Billing an insurer or scheme
* With only Bookings and Point of Sale: book with "bill to" a customer account that is the insurer (member number, pre-authorisation reference, the
  patient's **co-pay**). Checkout then makes **two invoices** from one screen: the patient's co-pay (paid at the desk) and the rest to the insurer's
  customer account (with the pre-authorisation reference in the memo). The split is exact to the cent.
* With the **Claims** unit on: "Bill an insurer" on the appointment opens a claim (the co-pay becomes the claim's excess). The insurer's part is then
  invoiced and followed from Claims (estimates, answers, ageing); the checkout shows those lines as "billed through Claims" and does not invoice them
  itself. Open point for the Claims owner: Claims' own customer invoice for the excess must not also be raised for an appointment the front desk already
  collected the co-pay for.

## Edit first
Prices and service items (as for the salon pack), your practitioners and rooms, and your insurers as customer accounts (or in Claims).

## What it does NOT do
No patient records, no prescriptions, no lab or imaging, no clinical notes, no insurer-portal integration, no automatic eligibility checks. Retention and
erasure of the administrative data follow `docs/privacy.md`.
