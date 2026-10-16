---
title: "Selling Offline: What Happens When the Till Loses Internet"
description: "How offline point-of-sale works, what can and cannot be done without a connection, how double counting is prevented and what to check when it reconnects."
h1: "Selling offline: what happens when the internet fails at the till"
date: 2026-10-15
topic: "Point of sale"
related: ["core-pos", "guide-choose-pos-multi-branch", "core-payments"]
faq:
  - q: "Will an offline sale be counted twice when the connection returns?"
    a: "It should not. A well-built till gives each sale its own number when it is made. If the same number arrives twice, the server keeps one sale and ignores the repeat."
  - q: "Can I take mobile-money payments offline?"
    a: "You can record a payment the customer has already made by typing in its transaction code. Sending a payment request to the customer's phone needs a connection."
  - q: "What happens to stock while offline?"
    a: "The till uses the last copy of stock it received. It may not know about sales at other tills until it reconnects. Decide a rule for items that are nearly out."
---

Power cuts and weak connections are normal in many places. A shop that cannot sell for an hour loses money and customers.

"Offline mode" sounds like a simple switch, but the details decide whether it is safe. This guide explains how a good offline till works, what must wait for a connection, and what to watch for.

## How an offline till works

An offline till does three things:

1. **It keeps a copy of what it needs** on the device: products, prices, tax rates, barcodes, customers, reasons and the receipt layout. It refreshes the copy whenever it is online.
2. **It saves each sale on the device first,** before telling the cashier it is done.
3. **It sends the sales to the server when the connection returns,** oldest first. It retries until each one is accepted.

The cashier keeps selling. Your books catch up later.

## What makes it trustworthy

### The sale is saved before it is confirmed

If the cashier sees "saved" and the device then loses power, the sale must still be there. The till should confirm only after the save worked.

If the device cannot store data safely, the till should refuse to sell offline. That is better than losing sales.

### Each sale has its own number

The device gives each sale a unique number the moment it is made. The server records a sale for that number once.

Say a reply is lost and the till sends the sale again. Or the page reloads in the middle of sending. The second attempt is recognised as a repeat and changes nothing. Without this, reconnecting could double your sales and your stock movements.

### Nothing is quietly dropped

Sometimes the server cannot accept a sale. A product may have been removed, or a rule may have been broken. The sale must not vanish.

It should go to a visible list marked "needs attention", with the reason, so a person can decide. You should also see how many sales are waiting and how old the oldest is.

### The offline receipt is honest

The server assigns the permanent receipt number when it accepts the sale. So a receipt printed offline should be marked as provisional, with a temporary number. Tell customers a copy may be reissued.

## What works offline and what does not

Ask of each action: does it need the server to be correct?

**Usually fine offline:**

- Selling for cash.
- Selling with card slips that are processed later.
- Mobile-money payments where the customer has paid and you type in the code.
- Scanning barcodes and searching products.
- Holding a sale and coming back to it.
- A price change, if the permission was saved on the device and a reason is recorded.

**Usually needs a connection:**

- Opening or closing a till session, because counts and approvals need the server.
- Sending a payment request to a customer's phone.
- Selling on credit, because the customer's limit and balance must be checked against current data.
- Returns and voids of sales already sent, because the original sale must be found.
- Anything that needs another person's approval.

A good till refuses these with a plain reason. It does not pretend.

## Risks of selling offline

### Old prices and stock

The till sells at the prices in its last copy. If you changed a price this morning and the till has not updated, it sells at the old price.

A good system shows "prices and stock as of" a time. It warns when the copy is old. If a sale used an outdated price, it flags the sale on sync instead of rejecting it, because the sale already happened.

### Selling the last item twice

Without live stock, two tills in different branches may both sell the last item. Pick a rule. You can allow negative stock and fix it at the next count. Or you can keep a safety margin for items that matter. Review negative stock either way.

### Wrong clocks

Offline sales carry the device's time. If the clock is wrong, the sale gets the wrong date. The system should record the device time, note how far it was from the server's time, and flag large gaps. Keep device clocks set to automatic.

### A long waiting list

Suppose a till has been offline for a day, or 50 sales are waiting. Something is wrong. The till should warn the user. It should not let them close the till without a prompt while sales are still waiting.

### Abuse

Checks are weaker offline, so it is a place for abuse. Make sure offline sales belong to the signed-in cashier's own till. They should carry the same reasons and limits as online sales. Include them in your daily review. A burst of offline sales followed by voids is as suspicious as it would be online.

## A checklist for your shop

Before you rely on offline selling:

- [ ] Disconnect a till. Sell five items with different payment types. Reconnect. Check that exactly five sales appear.
- [ ] Reload the page in the middle of a sale. Check the cart comes back.
- [ ] Close the browser with sales waiting. Reopen it. Check they are still waiting, then sent.
- [ ] Check your cashiers know what the status chip means: online, offline, sending, waiting, needs attention.
- [ ] Decide who looks at the "needs attention" list, and how often.
- [ ] Agree a rule for credit sales and returns while offline.
- [ ] Keep devices charged and set to update automatically.
- [ ] Test on the exact devices and browsers your cashiers use. Support differs.

## Make it part of the day

At the end of the day, someone should check that every till has an empty waiting list. They should clear the "needs attention" items and compare the day's takings with payments.

If a branch was offline for part of the day, expect its sales to arrive late. Match them after they have synced.

## How Ziira does it

The [Ziira till](/product/pos-and-till/) is a web till that keeps working with no network. It loads from the device after one online visit. It keeps a copy of the branch's products, prices, customers and reasons.

Each offline sale is saved on the device with its own number. It is sent when the connection returns, with retries and a "needs attention" list.

These need a connection: opening or closing a till, mobile-money prompts, credit on account, and returns or voids of sales already sent. Offline selling has not yet been tested on Safari or iOS.

For more on choosing a system, see [choosing POS software for several branches](/guides/choose-pos-multi-branch/).

Offline mode is only as good as its edge cases. Test them yourself before the day the internet fails.
