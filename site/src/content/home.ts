import type { Faq, Lang, ScreenKey } from "./types";

export interface HomeContent {
  id: "home";
  title: string; description: string; h1: string; lead: string; eyebrow: string;
  ctaPrimary: string; ctaSecondary: string; heroNote: string;
  /** The part of the H1 that gets the highlight. */
  h1Em: string;
  /** The words that get the hand-drawn underline (second sentence). */
  h1Und: string;
  /** Handwritten note beside the buttons: a true statement. */
  annotation: string;
  /** Only true statements. */
  trustLine: string[];
  /** The "everything included" strip under the hero: label, page, icon. */
  included: { t: string; page: string; icon: import("./integrations").IconName }[];
  /** Hero product mock: the example finding is labelled as an example with demo data. */
  mock: { badge: string; title: string; text: string; next: string; acts: string[]; frameLabel: string; cards: { area: string; title: string; text: string }[] };
  appsH2: string; appsLead: string;
  onePlace: { h2: string; text: string; points: string[]; hub: string; hubSub: string; alt: string };
  pricingTeaser: { h2: string; text: string; sets: string[]; link: string };
  scenariosH2: string; scenariosLead: string;
  scenarios: { mode: "run" | "watch" | "connect"; modeLabel: string; modeHint: string; t: string; d: string; why: string; page: string; link: string; visual: "till" | "branches" | "owing" | "daily" | "records" | "approval"; bullets: string[]; shot?: ScreenKey; color: number; icon: import("./integrations").IconName }[];
  startH2: string; startLead: string; startSteps: { t: string; d: string; page: string; link: string }[];
  productsH2: string; productsLead: string;
  products: { page: string; name: string; tag: string; text: string; points: string[]; link: string }[];
  stepsH2: string; steps: { n: string; t: string; d: string }[];
  screensH2: string; screensLead: string; screens: { key: ScreenKey }[]; /** alt text and captions live in src/lib/screens.ts, next to the pictures */
  findingsH2: string; findingsLead: string; findingsHead: string[]; findings: string[][]; findingsNote: string;
  compareH2: string; compareHead: string[]; compare: string[][]; compareNote: string;
  forH2: string; forItems: { t: string; d: string; link: string }[];
  trustH2: string; trust: { t: string; d: string }[]; trustNote: string;
  faq: Faq[]; faqH2: string;
  finalH2: string; finalText: string;
}

export const home: Record<Lang, HomeContent> = {
  en: {
    id: "home",
    title: "Ziira: Business System for Shops and Distributors",
    description: "Ziira runs sales, stock, buying, money and payroll for every branch, and checks it daily so owners know what needs attention. Works with your current system.",
    eyebrow: "One business system for growing and multi-branch businesses",
    h1: "Run your whole business from one system. Know what needs attention before it costs you.",
    h1Em: "whole business", h1Und: "before it costs you", annotation: "from the till to the balance sheet",
    lead: "Sales, stock, purchasing, accounting, payroll and customers in one place, with a daily check that watches it all and tells you what looks wrong, on screen and by email. WhatsApp is an add-on.",
    ctaPrimary: "Get started", ctaSecondary: "See how it works", heroNote: "Already have a system? Keep it. Ziira can look at it, without changing anything, and watch it for you.",
    trustLine: ["Sales, stock, finance and people in one system", "Many branches and companies, one view", "Reads your existing system without changing it"],
    included: [
      { t: "Selling and tills", page: "core-pos", icon: "till" }, { t: "Stock in every branch", page: "core-inventory", icon: "boxes" }, { t: "Suppliers", page: "core-purchasing", icon: "truck" },
      { t: "Customers who owe you", page: "core-customers", icon: "people" }, { t: "Books", page: "core-accounting", icon: "ledger" }, { t: "Staff pay", page: "core-people", icon: "person" }, { t: "The daily check", page: "intelligence-how", icon: "bell" },
    ],
    mock: {
      badge: "Example, demo data", title: "A cashier cancelled 14 sales after 9pm", text: "Far more cancellations than this cashier usually makes. The sales and the times are one tap away.", next: "Next step: ask the branch manager to explain.", acts: ["Ask for an explanation", "Why am I seeing this?"],
      frameLabel: "Command Center, shown with demo data",
      cards: [
        { area: "Finance, example", title: "Month-end close: 3 steps left", text: "Bank matched. Stock counted. Payroll waiting for approval." },
        { area: "Purchasing, example", title: "Supplier price up 17% on cement", text: "Your selling price has not changed." },
        { area: "People, example", title: "Payroll is ready for approval", text: "Deductions follow the rules you set." },
      ],
    },
    appsH2: "Everything your business does, in one place", appsLead: "Sales, buying, stock, books and people share one set of records, so nothing is typed twice. Pick a tile.",
    onePlace: {
      h2: "All your business on one platform",
      text: "Ziira is not separate programs stitched together. Selling, stock, buying, credit, books and pay share one product list, one customer list and one set of books, so a sale updates your stock, your money and your daily check without anyone typing it twice.",
      points: ["A sale lowers stock at the right branch, at the right cost", "The same sale lands in your books by itself", "The daily check reads all of it, so gaps show up"],
      hub: "One set of records", hubSub: "typed once", alt: "Diagram: selling, stock, buying, customers, payments, money, people and the daily check all connect to one set of records.",
    },
    pricingTeaser: { h2: "Simple pricing: start with what you need", text: "Choose the starting set that fits when you create your business. You can switch it later, and nothing you have entered is deleted.", sets: ["Retail", "Distribution", "Books", "Intelligence only", "Full"], link: "See plans and prices" },
    scenariosH2: "What you can do with Ziira", scenariosLead: "Five jobs a growing business needs done, in plain words.",
    scenarios: [
      { mode: "run", modeLabel: "Run it", modeHint: "The everyday work happens in Ziira.", t: "One set of records across sales, stock and books", d: "Selling, buying, stock, customers and accounts share one product list, one customer list and one set of books. A sale lowers stock and lands in your books without anyone typing it twice.", why: "Reports are ready when you need them, and always agree.", page: "core-accounting", link: "See accounting and reports", visual: "records", shot: "books", color: 7, icon: "ledger", bullets: ["A sale lowers stock at the right branch, at the right cost", "The same sale lands in your books by itself", "Profit and loss and other reports come straight from the books"] },
      { mode: "run", modeLabel: "Run it", modeHint: "The everyday work happens in Ziira.", t: "Every branch and company in one view", d: "Open Ziira and see sales, stock and cash for each branch side by side, without phoning managers or waiting for a report at month end.", why: "You can run many branches without standing in each one.", page: "solutions-multi-branch", link: "See Ziira for several branches", visual: "branches", shot: "command", color: 2, icon: "blocks", bullets: ["Sales, stock and cash for every branch on one screen", "Move stock between shops, and count it", "A branch manager sees only their own branch"] },
      { mode: "run", modeLabel: "Run it", modeHint: "The everyday work happens in Ziira.", t: "Approvals and control", d: "Decide who can do what. Voids, refunds, discounts and stock corrections need a reason, and where you set a limit, the person who creates something cannot approve it.", why: "Control without slowing the shop down.", page: "security", link: "How records are protected", visual: "approval", color: 5, icon: "person", bullets: ["Each person sees only what their role allows", "Limits by amount, with creator and approver kept apart where you set it", "A history of important actions that nobody can change or delete"] },
      { mode: "watch", modeLabel: "Watch it", modeHint: "Ziira checks the work and tells you.", t: "A daily check that watches it all", d: "Every day Ziira compares sales with the money received, stock with sales, and staff habits with what is normal for your business. You get the most important things first, with the proof, on screen and by email. WhatsApp is an add-on.", why: "You hear about a problem the same day, not at the next stock count.", page: "intelligence-complete", link: "Read the complete guide to the daily check", visual: "daily", shot: "finding", color: 8, icon: "bell", bullets: ["Money, stock, staff habits and credit are all checked", "Every alert links to the records behind it", "Approve a suggested fix with one tap, or ask in plain words"] },
      { mode: "run", modeLabel: "Run it", modeHint: "The everyday work happens in Ziira.", t: "Sell at the till, even when the internet is down", d: "The till keeps selling when the connection drops. Sales are saved on the device and sent once, when the connection returns, so nothing is lost and nothing is counted twice.", why: "Power and internet cuts stop being a reason to close the till.", page: "core-pos", link: "See how the till works", visual: "till", shot: "till", color: 1, icon: "till", bullets: ["Scan barcodes or search products; hold a sale and resume it later", "Cash, card slip and mobile-money payments recorded against the sale", "Every void, refund and discount carries a reason"] },
    ],
    startH2: "Start in three steps", startLead: "Create the business yourself, or tell us about it first.",
    startSteps: [
      { t: "Create your business", d: "Sign up, name your branches and choose what you need: the whole system, or only the daily check.", page: "get-started", link: "Get started" },
      { t: "Bring in what you have", d: "Add your products and customers, or connect the system, statements and reports you already use. Ziira only looks at them.", page: "intelligence-existing", link: "How connecting works" },
      { t: "Get your daily check", d: "Ziira checks the business every day and tells you what to look at first.", page: "intelligence-how", link: "How the daily check works" },
    ],
   
    productsH2: "Run it, watch it, connect it",
    productsLead: "Run the business, have it watched for you, and connect it to the tools you already use.",
    products: [
      { page: "product", name: "Run it", tag: "The business system", text: "Everything your shops and warehouses do every day, in one place, so nothing is typed twice.", points: ["Sell at the till, even when the internet is down", "Know the stock in every branch", "Buy from suppliers and see what you owe", "Keep your books and pay your staff"], link: "See what Ziira runs" },
      { page: "intelligence-how", name: "Watch it", tag: "Intelligence", text: "Every day, Ziira checks the numbers and tells you what to look at first, with the proof.", points: ["A short daily summary for the owner", "Alerts the same day when something looks wrong", "Suggestions you approve with one tap", "Ask a question in plain words and get an answer"], link: "See how it works, step by step" },
      { page: "integrations", name: "Connect it", tag: "Works with your tools", text: "Keep the tools you like. Ziira can look at them, and send you messages and payment requests.", points: ["Watch Odoo, ERPNext, Zoho Books or QuickBooks without changing them", "Check bank and mobile-money statements against sales", "Alerts and payments on your phone", "Let other apps talk to Ziira"], link: "See what Ziira connects to" },
    ],
    stepsH2: "What happens every day",
    steps: [
      { n: "1", t: "Bring in your numbers", d: "From Ziira's own tills and stock, or from your current system, till reports and statements." },
      { n: "2", t: "Ziira checks", d: "Records against hard evidence, and today against what is normal for your business." },
      { n: "3", t: "You are told", d: "A short summary or alert, most important first, with the records behind it." },
      { n: "4", t: "You decide", d: "Reply, and Ziira asks staff to explain, sends reminders or prepares something for you to approve." },
    ],
    screensH2: "See it working", screensLead: "Screens from the current Ziira web app, shown with demo data from a hardware business with three branches.",
    screens: [
      { key: "owing" },
      { key: "intel-actions" },
      { key: "addons" },
      { key: "brief" },
    ],
    findingsH2: "What an alert looks like", findingsLead: "Every alert comes with proof and a suggested next step. These examples are illustrative.",
    findingsHead: ["What Ziira noticed", "The proof", "Suggested next step"],
    findings: [
      ["A branch sold 4,400 more than it received", "Two cash sales with no matching cash or mobile-money payment", "Ask the cashier to explain"],
      ["Profit on a product fell from 9% to 4%", "The supplier raised the price 6% and your selling price did not change", "Update the selling price"],
      ["A credit order from a customer who is late paying", "A balance of 680,000, 45 days overdue", "Pause credit or ask for part payment"],
    ],
    findingsNote: "An alert is a question, not an accusation. Most have a good explanation, and Ziira records the answer.",
    compareH2: "Run everything in Ziira, or only watch your current system", compareHead: ["", "Everything in Ziira", "Daily checking only"],
    compare: [
      ["What it is", "The whole business system, with daily checking built in", "A watcher added on top of what you already use"],
      ["What it sees", "Every part of the business, live", "What your system or reports provide"],
      ["How fresh", "Live", "Daily, or when you upload"],
      ["Depth of checks", "Full, including who changed what", "Limited to what your system records"],
      ["What it can do for you", "Report, follow up, prepare and (within your rules) act", "Report and follow up; preparing and acting need Ziira's own data"],
      ["Switching", "You move your tills and books", "Nothing to switch"],
    ],
    compareNote: "You can start with daily checking only and move to the full system later. A guided step brings over products, customers, suppliers and balances.",
    forH2: "Pick your kind of business",
    forItems: [
      { t: "Retail shops", d: "Hardware, agrovets, pharmacies, wines and spirits, mini-marts.", link: "solutions-retail" },
      { t: "Distributors and wholesalers", d: "Buying in volume and selling on credit.", link: "solutions-distribution" },
      { t: "Multi-branch owners", d: "Owners who cannot be in every branch.", link: "solutions-multi-branch" },
    ],
    trustH2: "What you can rely on",
    trust: [
      { t: "Looks, never changes", d: "When Ziira watches your other system it can only look. You can take back its permission at any time." },
      { t: "Proof with every alert", d: "Each alert links to the records behind it." },
      { t: "Numbers from your records", d: "Totals and gaps are calculated from your data. The optional AI helper only writes the sentences." },
      { t: "Records that stay put", d: "Ledger entries, stock movements and the history of who did what cannot be edited or deleted." },
      { t: "You stay in charge", d: "Every business starts at reporting only. Ziira never moves money." },
      { t: "Honest limits", d: "No certifications claimed, no independent security test yet, and connections to outside services are marked where not yet proven live." },
    ],
    trustNote: "Read the full [security and privacy summary](@security).",
    faqH2: "Frequently asked questions",
    faq: [
      { q: "Do I need to replace my current system?", a: "No. Intelligence, the daily checking part of Ziira, can watch Odoo, ERPNext, Zoho Books, QuickBooks Online, or bank, mobile-money and spreadsheet reports. Move to the full Ziira later if you want to." },
      { q: "Who is it for?", a: "Retail and distribution businesses where staff handle money and stock while the owner is away: multi-branch shops, distributors selling on credit, and outlets with an absent owner or lots of cash." },
      { q: "Will it work in my country?", a: "Currency, tax codes, payroll deductions and other country details are entered by your business, so no country is built in. Services specific to a country, such as a mobile-money service, are added separately." },
      { q: "Does it work without internet at the till?", a: "Yes. The web till keeps selling offline and sends each sale once when the connection returns." },
      { q: "Can it change things in my accounts?", a: "Not unless you choose. Every business starts at reporting only. Moving up is your decision, and Ziira never moves money." },
      { q: "How much does it cost?", a: "See the [plans page](@pricing). We publish only real prices." },
    ],
    finalH2: "Start with what you need today",
    finalText: "Create a business in minutes, or tell us about yours.",
  },
};
