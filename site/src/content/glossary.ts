import type { Lang } from "./types";

export interface Term { term: string; def: string }

export const glossary: Record<Lang, Term[]> = {
  en: [
    { term: "ERP", def: "Enterprise resource planning software: one system for sales, stock, purchasing, payments, accounting and payroll, so the departments share the same records." },
    { term: "POS (point of sale)", def: "The place and software where a sale is made and paid for, such as a till at a shop counter." },
    { term: "Till session", def: "The period one cashier works a till, from opening cash to closing count, so the cash can be checked against what was sold." },
    { term: "Void", def: "Cancelling a sale or a line before or after payment. Frequent or large voids by one cashier are a classic warning sign, so each needs a reason." },
    { term: "Discount abuse", def: "Giving reductions that are not authorised, for example to friends or to hide a theft." },
    { term: "Reconciliation", def: "Comparing two sets of records that should agree, such as sales against mobile-money receipts or the ledger against a bank statement, and explaining every difference." },
    { term: "Mobile money", def: "Money held and moved through a mobile phone account, such as M-Pesa. In Ziira it is a generic payment method with a provider add-on." },
    { term: "Shrinkage", def: "Stock lost between purchase and sale through theft, damage, errors or waste." },
    { term: "Stock adjustment", def: "A correction to the quantity on hand. Because it changes stock without a sale, it should carry a reason and, above a limit, an approval." },
    { term: "Three-way match", def: "Checking that a supplier bill agrees with the purchase order and with the goods actually received before paying." },
    { term: "General ledger", def: "The master record of a business's accounts, built from journal entries." },
    { term: "Journal entry", def: "A balanced accounting record of debits and credits. In Ziira, posted entries are never edited; mistakes are reversed." },
    { term: "Chart of accounts", def: "The list of accounts a business uses to classify what it earns, owns and owes." },
    { term: "Separation of duties", def: "A control where the person who creates a record cannot also approve it." },
    { term: "Audit log", def: "A record of important actions: who did what and when. In Ziira it cannot be edited or deleted and is hash-chained." },
    { term: "Receivables ageing", def: "A report grouping what customers owe by how long it has been overdue." },
    { term: "Baseline", def: "What is normal for your business, learned from past data, such as a cashier's usual void rate. Unusual means well beyond it." },
    { term: "Alert", def: "One thing Intelligence flags, with severity, money at stake, a summary, a suggested action and the records behind it." },
    { term: "Brief", def: "A short daily or weekly message of what happened and what needs attention." },
    { term: "Read-only access", def: "Access that can look at data but not change it. Ziira connections only send read requests." },
    { term: "Using Intelligence on your existing system", def: "Intelligence running on top of a system you already use, without Ziira." },
    { term: "Action levels", def: "Ziira's four steps of autonomy: 1 report, 2 follow up, 3 prepare for approval, 4 act within limits. Every business starts at 1." },
    { term: "Webhook", def: "A message one system sends to another's web address when something happens, such as a sale being posted." },
    { term: "Idempotency", def: "The property that sending the same request twice has the same effect as once, so a retry cannot double a sale or a payment." },
  ],
};
