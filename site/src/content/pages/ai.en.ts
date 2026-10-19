import type { PageDef } from "../types";
import { pageFaq, pageHero } from "../ai";

/** The Ziira AI page (/ai/): rendered by components/AiSections.astro from content/ai.ts. */
export const aiEn: PageDef[] = [
  {
    id: "ai", slug: "ai", kind: "ai", schema: "core", cta: "general",
    title: pageHero.title, description: pageHero.description, h1: pageHero.h1, lead: pageHero.lead,
    eyebrow: "Ziira AI", short: "Ziira AI", glance: pageHero.glance, glanceTitle: "What Ziira AI does",
    blocks: [],
    faq: pageFaq,
    related: ["intelligence-how", "intelligence-complete", "intelligence-existing", "security"],
  },
];

/** "Who it is for": every business first, then examples. The industries are examples of coverage, not limits. */
export const solutionsFirst: PageDef[] = [
  {
    id: "solutions-every-business", slug: "solutions/every-business", parent: "solutions", kind: "page", cta: "general",
    title: "Ziira for Every Kind of Business: One System with AI",
    description: "Shops, distributors, pharmacies, salons, garages, clinics, gyms, consultants and schools: one system for sales, stock, bookings, jobs, claims and money.",
    h1: "One system for every kind of business", eyebrow: "Solutions · Every business", short: "Every business",
    lead: "Ziira is not a shop system with extras added. It is one set of records, one set of books and one AI that fit a market stall, a salon, a garage that works with insurers, a clinic, a gym, an agency or a chain of branches.",
    glance: ["The same core for every business: sell, stock, buy, money, people", "Parts that fit your work: bookings, jobs, claims, memberships, projects", "One AI across all of it", "From one till to many branches and companies"],
    blocks: [
      { h2: "What every business gets", ul: ["[Selling and invoicing](@core-pos), at a till or from the office, with returns and credit notes.", "[Stock in every branch](@core-inventory), counted and moved, with the cost of each item.", "[Buying from suppliers](@core-purchasing) and knowing what you owe.", "[Customers and credit](@core-customers), with limits, statements and reminders.", "[Accounting](@core-accounting) that fills itself as you work, and [payroll](@core-people) with your own rules.", "[Payments matched](@core-payments) to the sales they belong to.", "[Ziira AI](@ai) across all of it: the daily check, answers in plain words and suggestions you approve."] },
      { h2: "Then the parts that fit your work", ul: ["**Appointments and bookings:** diaries, staff and rooms, reminders, deposits, classes and an online booking page.", "**Jobs and repairs:** work orders, parts from stock, estimates the customer approves, and photos attached to the job.", "**Insurer and payer claims:** estimates sent to someone else who pays, their answer line by line, and the invoices split between them and the customer.", "**Memberships and packages:** plans, visit packs, credits, freezes and recurring invoices.", "**Projects and time billing:** timesheets, approvals, rate cards, retainers and invoices from approved time.", "**Files and photos** on any record, kept private to your business."] },
      { h2: "Examples of businesses that run on it", ul: ["[Shops and retail](@solutions-retail): hardware, agrovets, pharmacies, mini-marts.", "[Wholesale and distribution](@solutions-distribution): buy in volume, sell on credit.", "[Businesses with several branches](@solutions-multi-branch).", "[Salons, spas and barbers](@solutions-salons).", "[Garages and body shops](@solutions-garages), including insurer claims.", "[Clinics and dental practices](@solutions-clinics), for bookings and billing.", "[Gyms and studios](@solutions-gyms).", "[Consultants, agencies and accountants](@solutions-professional).", "Schools, tutors and training centres, using bookings, memberships and recurring invoices for classes and fees."], after: ["These are examples of what Ziira covers, not a list of limits. If your business sells, books, repairs, bills time or takes a membership, the same system fits."] },
      { h2: "Start with the set that fits", p: ["When you create your business you choose a starting set: Retail, Distribution, Services, Books, Intelligence only, or Everything. Starter data for a salon, a garage, a clinic, a gym or a professional practice can be switched on at sign-up or later in Add-ons. Nothing you enter is lost when you change the set."] },
      { h2: "From one till to many companies", p: ["Add branches and companies as you grow. Each branch manager sees their own branch, the owner sees all of them, and the AI answers each person only from what they are allowed to see."] },
    ],
    faq: [
      { q: "Is Ziira only for shops?", a: "No. It started with sales, stock and money, and it also covers appointments, jobs and repairs, insurer claims, memberships, and projects billed by time. Pick the starting set that fits and add the rest when you need it." },
      { q: "Does it cover my kind of business?", a: "If you sell, book, repair, bill time or take memberships, yes. Tell us about your business on the [get started page](@get-started) and we will say plainly what fits and what does not." },
    ],
    related: ["ai", "product", "pricing"],
  },
];

export const solutionsMore: PageDef[] = [
  {
    id: "solutions-salons", slug: "solutions/salons-and-spas", parent: "solutions", kind: "page", cta: "general",
    title: "Salon, Spa and Barber Software: Bookings, Stock and AI",
    description: "Diary and bookings with deposits and no-show rules, products on the shelf, commission and payroll, and AI that finds the money you are missing.",
    h1: "Salons, spas and barbers: fill the diary and keep what you earn", eyebrow: "Solutions · Salons and spas", short: "Salons and spas",
    lead: "Ziira runs the diary, the till, the products on your shelf and your staff pay in one place, and the AI tells you where money is slipping away.",
    blocks: [
      { h2: "What a salon gets", ul: ["A diary for stylists and rooms, with set-up time, clean-up time and processing time while colour sets.", "Deposits for long services, a patch-test flag, and reminders before the appointment.", "Cancellation and missed-appointment rules you set, and an online booking page.", "Retail products on the shelf with stock, and commission by service and by staff level.", "Starter data for a salon, spa or barber that you can edit, with example prices marked as examples."] },
      { h2: "What the AI watches", ul: ["Clients who did not turn up, and late cancellations.", "Long gaps in the diary and working time going unused.", "Finished appointments that were never invoiced, and deposits not paid.", "Tips held and not paid out.", "Supplier price rises that squeeze your margin on products, with a new price ready for you to approve."] },
      { h2: "Start small", p: ["Choose the Services starting set when you register and switch on the salon starter data. See also [Ziira for every kind of business](@solutions-every-business)."] },
    ],
    related: ["solutions-every-business", "ai", "get-started"],
  },
  {
    id: "solutions-garages", slug: "solutions/garages-and-body-shops", parent: "solutions", kind: "page", cta: "general",
    title: "Garage and Body Shop Software with Insurer Claims",
    description: "Job cards, parts from stock, photos, estimates customers approve, and insurer claims handled line by line, with AI that chases what is stuck.",
    h1: "Garages and body shops: jobs, parts and insurer claims in one place", eyebrow: "Solutions · Garages", short: "Garages",
    lead: "A job comes in with photos, parts are used from stock, an insurer answers an estimate line by line, and the invoice splits between the insurer and the customer. Ziira keeps all of it together.",
    blocks: [
      { h2: "What a garage gets", ul: ["Job cards with the vehicle, intake checklists and photos attached to the job.", "Stages that include waiting for the insurer and waiting for the customer.", "Parts taken from stock, and estimates the customer approves from a link.", "Courtesy cars, and repeat returns inside the warranty, watched for you."] },
      { h2: "When an insurer pays", ul: ["Send an estimate to the insurer and record its answer for each line: approved, counter-offered, rejected or more information needed.", "Extra damage found after teardown goes as a supplementary estimate, approved separately.", "Invoices split between the insurer and the customer, with the customer's excess.", "Ageing per insurer, and a flag when an insurer pays less than it approved."] },
      { h2: "What the AI watches", ul: ["Estimates an insurer has not answered, and counter-offers nobody replied to.", "Approved work that has not started, and extra work not sent to the insurer.", "Finished claims that were never invoiced, insurers paying late or paying short.", "Jobs stuck in a stage, and parts that are late."] },
    ],
    related: ["solutions-every-business", "ai", "get-started"],
  },
  {
    id: "solutions-clinics", slug: "solutions/clinics-and-dental-practices", parent: "solutions", kind: "page", cta: "general",
    title: "Clinic and Dental Practice Software for Bookings and Billing",
    description: "Appointments, reminders, recalls and billing to patients and insurers for clinics and dental practices. Administrative only, with no medical records.",
    h1: "Clinics and dental practices: appointments and billing that run themselves", eyebrow: "Solutions · Clinics", short: "Clinics",
    lead: "Ziira handles the front desk and the money: bookings, reminders, recalls, invoices and what insurers owe. It holds no clinical records.",
    blocks: [
      { h2: "What a clinic gets", ul: ["Appointment types with usual durations, practitioners and rooms, and a diary for each.", "Reminders and \"due again\" recalls for check-ups, and deposits where you want them.", "Bill to the patient, an insurer or scheme, or an employer, with member and pre-authorisation references.", "Starter data for a clinic or dental practice that you can edit."] },
      { h2: "What the AI watches", ul: ["Missed appointments and late cancellations.", "Finished appointments with no invoice.", "Insurers paying later than usual, or paying less than approved."] },
      { h2: "A clear limit", callout: { tone: "info", title: "Administrative only", text: "Ziira keeps appointments and billing. It holds no diagnoses, prescriptions, results or treatment notes, so it is not a medical record system." } },
    ],
    related: ["solutions-every-business", "ai", "get-started"],
  },
  {
    id: "solutions-gyms", slug: "solutions/gyms-and-studios", parent: "solutions", kind: "page", cta: "general",
    title: "Gym and Fitness Studio Software: Memberships and Billing",
    description: "Membership plans, visit and class packs, freezes, recurring invoices and classes for gyms and studios, with AI that spots members about to leave.",
    h1: "Gyms and studios: keep members and bill them on time", eyebrow: "Solutions · Gyms", short: "Gyms and studios",
    lead: "Plans, packs, classes and recurring invoices in one place, and an AI that notices who has stopped coming before they cancel.",
    blocks: [
      { h2: "What a gym gets", ul: ["Membership plans: monthly, annual, contract with a minimum term, off-peak, day and week passes, and a free trial.", "Visit and class packs that expire, personal-training sessions, and credits that carry over if you choose.", "Freezes, a joining fee, guest passes and recurring invoices made for you.", "Classes with a diary and booking, and starter data you can edit with example prices marked as examples."] },
      { h2: "What the AI watches", ul: ["Members who stopped coming.", "Members who have not paid, and recurring invoices that failed.", "Memberships ending soon, and packs about to expire with credits left.", "How much membership income is at risk."] },
    ],
    related: ["solutions-every-business", "ai", "get-started"],
  },
  {
    id: "solutions-professional", slug: "solutions/consultants-and-agencies", parent: "solutions", kind: "page", cta: "general",
    title: "Software for Consultants, Agencies and Accountants",
    description: "Track time, approve timesheets, bill hourly, fixed, capped or retainer fees, and see unbilled work and projects over budget, with AI that explains it.",
    h1: "Consultants, agencies and accountants: bill every hour you work", eyebrow: "Solutions · Professional services", short: "Consultants and agencies",
    lead: "Time, expenses, approvals and invoices in one system, and an AI that tells you what work has not been billed.",
    blocks: [
      { h2: "What a practice gets", ul: ["Time entries and timers, weekly timesheets, and approval by a second person.", "Rates by title, and fee types: hourly, fixed fee with milestones, capped, or retainer.", "Expenses with a receipt photo, re-billed with an optional markup.", "One invoice from the approved time, and engagement templates such as monthly bookkeeping or a campaign project."] },
      { h2: "What the AI watches", ul: ["Work done but not invoiced, and how long it has waited.", "Projects over budget, retainers nearly used up, and less of the time being billable.", "Timesheets not sent in or waiting for approval."] },
      { h2: "A clear limit", callout: { tone: "info", title: "No client money", text: "Ziira does not hold or account for money held on behalf of a client, such as a lawyer's client account. Keep it in a separate account." } },
    ],
    related: ["solutions-every-business", "ai", "get-started"],
  },
];
