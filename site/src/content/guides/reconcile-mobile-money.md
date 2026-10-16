---
title: "Reconcile Mobile-Money Statements to Your Sales"
description: "A step-by-step routine to match mobile-money receipts to sales: what to download, how to match by code, how to treat mismatches and how often to do it."
h1: "How to reconcile mobile-money statements to your sales"
date: 2026-10-15
topic: "Cash and payments"
related: ["guide-month-end-close", "intelligence-source-mobile-money", "core-payments"]
faq:
  - q: "How often should I reconcile?"
    a: "Daily if mobile money is your main way of getting paid. Weekly at the very least. A difference is far easier to explain the next morning than a month later."
  - q: "What if the customer paid but the code was not recorded at the till?"
    a: "Match on amount and a short time window instead. Then fix the habit: do not let a mobile-money sale finish without the transaction code."
  - q: "Can I reconcile if the statement is a PDF?"
    a: "Yes, but copying rows by hand is slow and easy to get wrong. A tool that reads PDF or Excel statements saves the typing. Check the totals against the statement's opening and closing balances."
---

If customers pay through a mobile-money till or paybill, the company's statement is the most reliable record of what you were paid. Your sales records show what your staff typed in.

Reconciling means comparing the two every day and explaining every difference. It catches payments that never arrived, wrong amounts, duplicates, and the cashier who records a mobile-money sale that was never paid.

## What you compare

- **Your side:** every sale marked as paid by mobile money. You need the amount, the time, the branch and, ideally, the transaction code.
- **Their side:** the statement for the same period. Each line has a transaction code, a date and time, an amount, the payer and a running balance.

The goal is simple. Every sale has a statement line. Every statement line coming in has a sale.

## Step 1: Pick the period and download the statement

Pick a clear period, such as yesterday from midnight to midnight. Download the statement for exactly that period for each till or paybill.

If several branches share one till, split by branch afterwards. If each branch has its own till, reconcile each one separately.

Check the statement's own sums. Opening balance, plus money in, minus money out, should equal the closing balance. If not, the file is incomplete. Do not start matching on a broken file.

## Step 2: Export your sales for the same period

From your till or ERP, export the sales paid by mobile money for the same dates. You need the receipt number, time, cashier, branch, amount and transaction code.

Use the same time zone as the statement. Different time zones create fake differences near midnight.

## Step 3: Match by code first

A transaction code is unique, so it is the best way to match. For each sale with a code, find the statement line with the same code. Then check three things:

1. **Amount:** does it equal the sale total, or the part paid by mobile money?
2. **Time:** is the payment within a few minutes of the sale?
3. **Direction:** is it money in, not out?

If all three agree, the match is clean. Mark both lines as matched.

## Step 4: Match the rest by amount and time

Some sales have no code, or a mistyped one. For these, look for a statement line with the same amount within a short window, such as 10 minutes. It must not already be matched.

This is weaker evidence. Mark it "probable" and add a note. Take care when several customers pay the same round amount at about the same time. A probable match is not proof.

## Step 5: Sort out what is left

You now have two lists of leftovers.

### Sales with no statement line

These are the ones to worry about. Possible reasons:

- The customer has not paid yet, or paid to a different till or number.
- The cashier typed the wrong code or amount.
- The sale was marked mobile money but paid in cash, and the cash was kept.
- The sale was invented, or was voided or refunded but still counted.
- The statement period or time zone differs from your sales period.

### Statement lines with no sale

Money arrived that your books do not explain. Possible reasons:

- A customer paid a debt, a deposit or an invoice you recorded elsewhere.
- A sale was not recorded, or was entered as cash.
- A duplicate: the customer paid twice and is owed a refund.
- A transfer between your own accounts, or a refund coming back.

Write a note next to each line. "Unknown" is acceptable for a day. It should not stay unknown for a month.

## Step 6: Write down the result and act

Record the day's result in a simple form:

- Total in on the statement.
- Total of matched sales.
- Value of sales with no payment.
- Value of payments with no sale.
- Who checked.

The value of sales with no payment matters most for loss.

Then act on the pattern, not just the line. If one cashier appears in most of the unmatched sales, ask them to explain, with the records in front of you. If unmatched payments are customers paying old invoices, give the cashier a way to record them.

## Habits that make this easier

- **Require the transaction code** on every mobile-money sale. Do not let the sale finish without it.
- **Reconcile every day,** and put one person in charge. That person should not also take the money.
- **Keep statements** in a folder or in your system, so you can answer a question months later.
- **Keep payment types apart:** mobile money, card slips and bank deposits.
- **Check the bank too.** Cash you bank should match the cash you counted. Payments from the mobile-money company should arrive in your bank account.

## Doing it with software

This routine is mechanical, so software suits it. [Ziira](/product/payments-and-reconciliation/) records every payment with its method and outside reference. It imports statements, matches them to sales and flags what is left.

If you keep your current system, [Ziira Intelligence can read a mobile-money statement](/intelligence/on-your-existing-system/mobile-money-statements/) as a PDF, Excel, CSV or photo and compare it with your sales export. It matches the code first, then amount and time.

It is open about one limit. The match is not always one-to-one, and it is only as good as how consistently the code is recorded.

Whatever you use, the rule stands. Every payment you received should be explained by a sale. Every sale marked as paid should be explained by a payment.
