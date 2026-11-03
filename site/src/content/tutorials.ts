/** The video tutorials page: one section per kind of business. A section with `videos` shows them; one without shows "coming soon". Files live in public/tutorials/<key>/ (video and a same-named .jpg poster). */
export interface Tutorial { file: string; title: string; seconds: number; text: string; points: string[] }
export interface TutorialSection { key: string; label: string; page: string; blurb: string; videos: Tutorial[] }

export const tutorialSections: TutorialSection[] = [
  {
    key: "gyms", label: "Gyms and studios", page: "solutions-gyms",
    blurb: "Follow a gym owner from an empty account to a club that runs. Everything is built on screen from nothing: no sample members and no example plans.",
    videos: [
      { file: "n1-create-your-account", title: "Create your account", seconds: 187, text: "Start from nothing: register, and see an empty gym.",
        points: ["Choosing what you need", "Business name and country", "Your sign-in, and confirming your email", "The short Getting started list"] },
      { file: "n2-make-your-first-plan", title: "Make your first plan", seconds: 209, text: "A name and a price are enough. Then a yearly plan and a day pass.",
        points: ["The quick start: name, monthly price, joining fee", "An Annual plan and a Day pass", "More options for later"] },
      { file: "n3-sign-up-your-first-member", title: "Sign up your first member", seconds: 230, text: "Add a customer, sign them up, make the first invoice and take the payment.",
        points: ["Signing up a member to a plan", "The first invoice", "Taking a cash payment and the receipt", "Card number, photo and emergency contact"] },
      { file: "n4-let-people-in", title: "Let people in", seconds: 178, text: "The check-in desk, a card number, a name, a stranger, and the self check-in keypad.",
        points: ["Check in by card number or name", "Allowed and Not allowed", "Self check-in for members", "Every visit is saved"] },
      { file: "n5-packages-terms-rules", title: "Packages, terms and rules", seconds: 341, text: "Optional extras for later: bundles like ten classes, your terms, and late-payment rules.",
        points: ["Packages of classes, visits and training", "Writing and publishing your terms", "Days of grace, reminders and holds"] },
      { file: "n6-get-paid-and-late-payments", title: "Get paid, and see who is late", seconds: 140, text: "Who owes you money and how late they are, and how to take full and part payments.",
        points: ["The Money owed page", "Taking a payment in full, or in part", "Your late-payment rules"] },
      { file: "n7-holds-plan-changes-cancellations", title: "Holds, plan changes, cancellations", seconds: 137, text: "Put a membership on hold, upgrade, move to a cheaper plan, and cancel.",
        points: ["Put on hold, and resume", "Upgrade now with the price shown first", "A cheaper plan starts at renewal", "Cancel with a reason"] },
      { file: "n8-classes-lockers-vouchers", title: "Classes, lockers, vouchers", seconds: 112, text: "Sell a class pack, run a class, give out a locker and sell a gift voucher.",
        points: ["Selling a pack of 10 classes", "The timetable, booking and who came", "Lockers", "Gift vouchers"] },
    ],
  },
  { key: "retail", label: "Shops and retail", page: "solutions-retail", blurb: "The till, stock and cash for a shop, from the first sale to the end-of-day count.", videos: [] },
  { key: "distribution", label: "Wholesale and distribution", page: "solutions-distribution", blurb: "Buying in volume, selling on credit, and knowing who owes you.", videos: [] },
  { key: "salons", label: "Salons, spas and barbers", page: "solutions-salons", blurb: "The diary, deposits, products and staff commission.", videos: [] },
  { key: "garages", label: "Garages and body shops", page: "solutions-garages", blurb: "Jobs, parts, photos, deposits and insurer claims.", videos: [] },
  { key: "clinics", label: "Clinics and dental practices", page: "solutions-clinics", blurb: "Appointments and billing for patients.", videos: [] },
  { key: "professional", label: "Consultants and agencies", page: "solutions-professional", blurb: "Time, approvals and retainers.", videos: [] },
];
