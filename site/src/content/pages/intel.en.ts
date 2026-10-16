import type { PageDef } from "../types";
import { faq as guideFaq } from "../completeGuide";
import { totals } from "../../lib/catalog";
import { availability, ifAvailable, isAvailable, soonKeys, type AvailKey } from "../availability";

const ERPS: AvailKey[] = ["erpnext", "odoo", "zoho-books", "quickbooks"];
const erpList = ERPS.filter(isAvailable).map((k) => availability[k].name).join(", ");
const channelNames: [AvailKey, string][] = [["email", "email"], ["sms", "SMS"], ["whatsapp", "WhatsApp"]];
const channels = channelNames.filter(([k]) => isAvailable(k)).map(([, n]) => n);
const channelLine = channels.length ? `You see it in the app and by ${channels.join(", ").replace(/, ([^,]*)$/, " or $1")}.` : "You see it in the app, ready when you open it.";
const comingNext = soonKeys().filter((k) => k !== "subscription-payments").map((k) => `**${availability[k].name}:** ${availability[k].note}`);
const aiFaq = isAvailable("ai-helper") ? "No. Totals and gaps are worked out from your records. The AI helper only writes sentences, it is off until an Owner agrees, and an answer with a number it cannot trace to your records is thrown away." : "No. Totals and gaps are always worked out from your records, never guessed. An optional helper that explains them in plain words is coming soon.";

export const intelEn: PageDef[] = [
  {
    id: "intelligence-how", slug: "intelligence/how-it-works", kind: "steps", schema: "intelligence", cta: "intelligence",
    title: "Daily Fraud and Leak Check: How Intelligence Works",
    description: "How Ziira finds mistakes and losses in your sales, stock, cash and staff records every day, in six short steps, and what you get each morning.",
    h1: "How Intelligence works, step by step",
    eyebrow: "Intelligence", short: "How Intelligence works",
    lead: "Every day Ziira checks your records and tells you what looks wrong, with the proof. Here is how, in six steps.",
    glance: ["Six steps, from your records to a decision", "What it checks, with the number of checks", "What you get each morning", "What it never does: it never moves money"],
    glanceTitle: "On this page",
    how: {
      minutes: 3,
      story: {
        title: "Imagine an accountant who never sleeps",
        paragraphs: [
          "Picture a careful accountant who, every night after you close, goes through every sale, every cancelled receipt, every stock count, every payment and every bill, in every branch.",
          "Not once a month. Every night. And when you walk in the next morning, there is a short note on your desk.",
        ],
        noteTitle: "This morning's note",
        note: [
          "Ruiru: a cashier cancelled 14 sales after 9pm. Usually 2.",
          "The cement supplier's price went up 17% on your last order.",
          "Mary Wanjiku's invoice is now 45 days late.",
          "Thika banked KES 12,000 less than it sold.",
        ],
        noteCaption: "An example note, made up for this page",
        after: [
          "You did not ask for any of it. You did not dig through a report. You read four lines, and you knew exactly where to look.",
          "That accountant is Ziira Intelligence.",
        ],
        teaser: "But how does it know what is unusual for a business it has only just met? And what does it do with what it finds? Here it is, in six steps.",
      },
      steps: [
        { title: "Ziira reads your records", text: [
          "It reads your sales, stock, money and staff records.",
          `They come from Ziira itself, or from the bank and mobile-money statements and sales files you upload.${erpList ? ` Ziira can also read ${erpList.replace(/, ([^,]*)$/, " and $1")}.` : ""}`,
          "On anything you connect or upload, Ziira only looks. It never changes anything in it.",
        ], result: "The records the checks need are in one place.", img: { key: "connect-add", alt: "The Add a connection page: drop a bank or mobile-money statement or a sales, stock or expense file", caption: "Adding a system or a statement (demo data)" } },
        { title: "It checks them against your normal", text: [
          "Ziira runs its checks by itself every six hours, including overnight.",
          "It compares each record with what is normal for you, not with one rule for everyone. A busy branch and a quiet branch get different limits.",
          "Examples: cashier cancellations, cash against sales, stock that vanished, late customers, supplier price jumps, odd accounting entries.",
        ], result: "Each check says clearly: normal, or worth a look.", img: { key: "connect", alt: "The What Ziira can check panel, grouping checks into cash and sales, customers and credit, suppliers, stock, books and people", caption: "What Ziira can check (demo data)" } },
        { title: "Anything wrong becomes a thing to look at", text: [
          "A check that finds a problem creates a thing to look at. It says how urgent it is, how much money is involved, and what to do next.",
          "It also shows the proof: the exact sales, stock moves or entries behind it.",
          "You find them under Things to look at in the app.",
        ], result: "One clear card with the proof, not a long report.", img: { key: "finding", alt: "One thing to look at: supplier invoices that are overdue, with what we noticed, why it matters, what you can do next and the facts", caption: "A thing to look at, with its proof (demo data)" } },
        { title: "Every morning you get a short summary", text: [
          "It lists yesterday's main figures and the few things that need you, most important first.",
          channelLine,
          "Urgent things can reach you the same day.",
        ], result: "Two minutes with your morning coffee tells you where to look.", img: { key: "brief", alt: "A preview of the daily summary listing yesterday's figures such as cash balance, stock value and overdue balances", caption: "The daily summary (demo data)" } },
        { title: "You look, hand it on, or say it is fine", text: [
          "Open a thing to look at and read the proof.",
          "Then give it to someone, ask a manager to explain, or choose Not a problem.",
          "A closed one does not come back unless something new happens.",
        ], result: "Every answer is recorded with who gave it and when.", img: { key: "findings", alt: "The Things to look at page: cards for each thing, most urgent first, with Look into it, Give to someone, Not a problem and Remind me later", caption: "Everything to look at, most important first (demo data)" } },
        { title: "Optional: let Ziira do routine jobs", text: [
          "You can let Ziira prepare drafts, send reminders to late customers, or do routine jobs for you.",
          "You choose how far it goes, and you set the limits. Every business starts at report only.",
          "Ziira never moves money.",
        ], result: "The routine jobs you allow get done, and each one is recorded.", img: { key: "intel-actions", alt: "How much Ziira does for you: Watch, Ask, Prepare and Act for me, with Watch selected, and a note that Ziira never moves money", caption: "Choose how much Ziira does for you (demo data)" } },
      ],
    },
    blocks: [
      ...(comingNext.length ? [{ h2: "Coming next", ul: comingNext, after: ["Want one of these first? [Tell us](@get-started) and we will let you know the day it opens."] }] : []),
    ],
    faq: [
      { q: "Does Intelligence change anything in my system?", a: "No. On anything you connect or upload, it can only look. Every business starts at report only, which changes nothing." },
      { q: "Is the AI making up the numbers?", a: aiFaq },
      { q: "How long before the alerts are useful?", a: "Expect some wrong alerts in the first weeks. Ziira reads past months to learn your normal, and you can change the limits." },
    ],
    related: ["intelligence-complete", "intelligence-existing", "integrations"],
  },
  {
    id: "intelligence-existing", slug: "intelligence/on-your-existing-system", parent: "intelligence-how", kind: "sources", avail: ["erpnext", "odoo", "zoho-books", "quickbooks"], children: true, schema: "intelligence", cta: "intelligence", hero: "connect-add",
    title: "Fraud Detection for the ERP You Already Use (Read-Only)",
    description: "Keep your bank and mobile-money statements and sales files. Ziira reads them view only and checks the business daily. ERP connections are coming soon.",
    h1: "Use Intelligence with the system you already have",
    eyebrow: "Intelligence · Your existing system", short: "On your existing system",
    lead: "Not ready to move your books and tills? You do not have to. Ziira can look at what you keep (a till report, a bank or mobile-money statement, a sales or stock export), keep a copy for checking, and run the same daily checks, with alerts and a daily summary. It never changes anything in your system.",
    blocks: [
      { h2: "Looking only, never changing", ul: [
        "Ziira only ever looks. It never writes to, edits or deletes anything in your system, and a file you upload never connects to anything.",
        "Access is a separate key or approval made just for Ziira, which you can take back at any time. Nobody shares a password.",
        "Keys are stored encrypted, never shown again, and kept out of logs.",
        "A file you upload is read and its lines are kept for checking; the file itself is not kept.",
      ], after: ["More in the guide to [connecting your ERP safely with read-only access](@guide-read-only-access)."] },
      { h2: "Pick your source", cards: true, p: ["Each page says what is read, how to create the access, what is checked and what is not."] },
      { h2: "How it starts", ol: [
        "Choose \"keep my system\" when you register. You get Home, Intelligence, Connected systems and Settings.",
        "Add a connection: drop in a statement or an export file.",
        "Map the system's branches to your branches, or leave them at company level.",
        "Ziira reads, checks and starts sending alerts and briefs. Only complete days are judged, so a statement that ends early never makes a quiet day look bad.",
      ] },
      { h2: "What the checks cover", table: { head: ["Area", "Examples of what is flagged"], rows: [
        ["Cash and sales", "Sales with no matching statement line; cash sales well above deposits; a branch far below its weekday normal"],
        ["Controls", "Unusual void, refund and discount rates per cashier; one large exception; sales at odd hours; sales entered days late"],
        ["Customers", "Overdue customers; credit to overdue customers; customers paying slower"],
        ["Suppliers", "Supplier price rises; duplicate bills and payments"],
        ["Stock", "Large, odd-hour or back-dated adjustments; shrinkage by product; negative stock"],
        ["Books", "Manual journals that are large, round, odd-hour, back-dated or self-approved; unusually high expenses; money received matching no sale"],
        ["People", "New users appearing in the source system"],
      ] }, after: ["A check whose data was never connected stays silent, and the What Ziira can check panel shows what can and cannot be checked today and which connection would switch more on."] },
      { h2: "What to expect", ul: [
        "What can be checked depends on what the source records. A till export without voids or discounts cannot show cashier habits.",
        "Files give daily data at best; connected systems are read on a schedule (daily unless you change it).",
        "Matching a statement line to a sale uses the payment code, or else the amount and time. It is not always one-to-one, and works as well as your system records payment codes.",
        "On a connected system expect reporting and follow-ups (levels 1 and 2). Prepared and automatic actions (levels 3 and 4) work only on data in Ziira itself.",
      ] },
      { h2: "Moving to Ziira later", p: ["If you later move to [Ziira](@product), a guided step proposes products, customers, suppliers, opening stock and balances from what Ziira has already read, checks them, and lets you undo the opening balances. Nothing is ever deleted automatically."] },
      { h2: "When both run", p: ["If Ziira itself runs the same area as a connected system, the old system's check for that area stays quiet for that branch, and the app offers to pause the connection or keep both. Every alert says where it comes from."] },
    ],
    faq: [
      { q: "Do I have to switch my POS or ERP?", a: "No. That is the point of using Intelligence on your existing system. You can move to Ziira later if you want to." },
      { q: "What about SAP Business One or Sage?", a: "They are not supported yet. Older systems that can export reports can use the file route." },
      { q: "Does it work with no system at all?", a: "Yes, with the bank and mobile-money statements and a sales export. Checks cover cash, sales and basic stock." },
    ],
    related: ["intelligence-how", "guide-read-only-access", "integrations"],
  },
  {
    id: "intelligence-complete", slug: "intelligence/complete-guide", parent: "intelligence-how", kind: "complete", schema: "intelligence", cta: "intelligence",
    title: "Ziira Intelligence: Complete Guide to Business Checks",
    description: "How Ziira Intelligence works end to end: what it checks every day, where its data comes from, alerts, the AI helper and actions, in plain words.",
    h1: "Ziira Intelligence: the complete guide to daily business checks",
    eyebrow: "Intelligence · The complete guide", short: "The complete guide",
    lead: "The whole of Intelligence in one page, for the owner rather than the technician.",
    blocks: [],
    faq: guideFaq,
    related: ["intelligence-how", "intelligence-existing", "pricing", "get-started"],
  },
];
