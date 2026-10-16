import type { PageDef } from "../types";
import { faq as guideFaq } from "../completeGuide";
import { totals } from "../../lib/catalog";

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
      steps: [
        { title: "Ziira reads your records", text: [
          "It reads your sales, stock, money and staff records.",
          "They come from Ziira itself, or from a system you already use: Odoo, ERPNext, Zoho Books, QuickBooks Online, or your bank and mobile-money statements.",
          "On a system you already use, Ziira only looks. It never changes anything in it.",
        ], result: "The records the checks need are in one place.", img: { key: "connect-add", alt: "The Add a connection page: drop a bank or mobile-money statement or a sales, stock or expense file, or choose ERPNext, Odoo, QuickBooks Online or Zoho Books", caption: "Adding a system or a statement (demo data)" } },
        { title: "It checks them against your normal", text: [
          "Ziira runs its checks by itself every six hours, including overnight.",
          "It compares each record with what is normal for you, not with one rule for everyone. A busy branch and a quiet branch get different limits.",
          "Examples: cashier cancellations, cash against sales, stock that vanished, late customers, supplier price jumps, odd accounting entries.",
        ], result: "Each check says clearly: normal, or worth a look.", img: { key: "connect", alt: "The What Ziira can check panel, grouping checks into cash and sales, customers and credit, suppliers, stock, books and people", caption: "What Ziira can check (demo data)" } },
        { title: "Anything wrong becomes a thing to look at", text: [
          "A check that finds a problem creates a thing to look at. It says how urgent it is, how much money is involved, and what to do next.",
          "It also shows the proof: the exact sales, stock moves or entries behind it.",
          "The app used to call these findings, so you may still see that word on some screens.",
        ], result: "One clear card with the proof, not a long report.", img: { key: "finding", alt: "One thing to look at: a cash close that ended KES 530 over, with its suggested next step, the figures it is based on, and its history", caption: "A thing to look at, with its proof (demo data)" } },
        { title: "Every morning you get a short summary", text: [
          "It lists yesterday's main figures and the few things that need you, most important first.",
          "You see it in the app and by email. You can add SMS, or WhatsApp with the WhatsApp add-on.",
          "Urgent things can reach you the same day.",
        ], result: "Two minutes with your morning coffee tells you where to look.", img: { key: "brief", alt: "A daily summary for the demo business listing yesterday's figures such as cash balance, stock value and overdue balances", caption: "The daily summary (demo data)" } },
        { title: "You look, hand it on, or say it is fine", text: [
          "Open a thing to look at and read the proof.",
          "Then give it to someone, ask a manager to explain, or mark it not a problem.",
          "A closed one does not come back unless something new happens.",
        ], result: "Every answer is recorded with who gave it and when.", img: { key: "findings", alt: "The list of things to look at, most important first, with the total amount involved and a filter", caption: "Everything to look at, most important first (demo data)" } },
        { title: "Optional: let Ziira do routine jobs", text: [
          "You can let Ziira prepare drafts, send reminders to late customers, or do routine jobs for you.",
          "You choose how far it goes, and you set the limits. Every business starts at report only.",
          "Ziira never moves money.",
        ], result: "The routine jobs you allow get done, and each one is recorded.", img: { key: "intel-actions", alt: "Settings, Intelligence actions: four levels from report only to routine actions, with the first selected, and a note that Ziira never moves money", caption: "Choose how much Ziira does for you (demo data)" } },
      ],
    },
    blocks: [
      { h2: "Not tested live yet", p: ["Email, SMS, WhatsApp, the AI helper and the connections to Odoo, ERPNext, Zoho Books and QuickBooks Online were built from public instructions and tested against stand-ins. They have not yet run against the real services. Test them on a demo account first."] },
    ],
    faq: [
      { q: "Does Intelligence change anything in my system?", a: "No. On a system you already use, it can only look. Every business starts at report only, which changes nothing." },
      { q: "Is the AI making up the numbers?", a: "No. Totals and gaps are worked out from your records. The optional AI helper only writes sentences, it is off until an Owner agrees, and an answer with a number it cannot trace to your records is thrown away." },
      { q: "How long before the alerts are useful?", a: "Expect some wrong alerts in the first weeks. Ziira reads past months to learn your normal, and you can change the limits." },
    ],
    related: ["intelligence-complete", "intelligence-existing", "integrations-whatsapp"],
  },
  {
    id: "intelligence-existing", slug: "intelligence/on-your-existing-system", parent: "intelligence-how", kind: "sources", children: true, schema: "intelligence", cta: "intelligence", hero: "connect-add",
    title: "Fraud Detection for the ERP You Already Use (Read-Only)",
    description: "Keep Odoo, ERPNext, Zoho Books, QuickBooks or your statements. Intelligence reads them read-only and checks the business daily.",
    h1: "Use Intelligence with the system you already have",
    eyebrow: "Intelligence · Your existing system", short: "On your existing system",
    lead: "Not ready to move your books and tills? You do not have to. Ziira can look at the system you keep (an ERP, a till report, a bank or mobile-money statement), keep a copy for checking, and run the same daily checks, with alerts and a daily summary. It never changes anything in your system.",
    blocks: [
      { h2: "Looking only, never changing", ul: [
        "Ziira only ever looks. It never writes to, edits or deletes anything in your system, and a file you upload never connects to anything.",
        "Access is a separate key or approval made just for Ziira, which you can take back at any time. Nobody shares a password.",
        "Keys are stored encrypted, never shown again, and kept out of logs.",
        "A file you upload is read and its lines are kept for checking; the file itself is not kept.",
      ], after: ["More in the guide to [connecting your ERP safely with read-only access](@guide-read-only-access)."] },
      { h2: "Pick your source", cards: true, p: ["Each page says what is read, how to create the access, what is checked and what is not."] },
      { h2: "How it starts", ol: [
        "Choose \"keep my system\" when you register. You get Home, Command Center, Alerts, Connected systems and Settings.",
        "Add a connection. For an ERP you create a limited, view-only key or approve a view-only app; for statements you drop in a file.",
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
      ] }, after: ["A check whose data was never connected stays silent, and a Coverage panel shows what can and cannot be checked today and which connection would switch more on."] },
      { h2: "Honest limits", ul: [
        "What can be checked depends on what the source records. A till export without voids or discounts cannot show cashier habits.",
        "Files give daily data at best; connected systems are read on a schedule (daily unless you change it).",
        "Matching a statement line to a sale uses the payment code, or else the amount and time. It is not always one-to-one, and works as well as your system records payment codes.",
        "The four ERP connections have been tested against sample data and have not yet been run against a real ERPNext, Odoo, Zoho Books or QuickBooks account. A first live run is planned on a demo or test company.",
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
