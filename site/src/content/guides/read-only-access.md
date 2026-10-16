---
title: "Read-Only Access: Connect Your ERP Safely"
description: "How to let a reporting or monitoring tool look at your ERP without risk: a separate user that can only view, safe keys, tests, logs and how to cut access."
h1: "Read-only access: how to connect your ERP safely"
date: 2026-10-15
topic: "Security"
related: ["intelligence-existing", "security", "integrations-api"]
faq:
  - q: "If a tool says it is read-only, is that enough?"
    a: "No. That is only the tool's promise. Give it a separate user that can only view. Then your own system refuses any change, even if the tool has a fault."
  - q: "Should I share my own login?"
    a: "No. You cannot limit a shared login. You cannot cut it off without locking yourself out. And your records cannot show who did what. Make a separate user for the tool."
  - q: "How do I know what a connected tool reads?"
    a: "Look at what the user or approval you gave it can see. Check your system's access log if it has one. Ask the vendor for a list of the records it reads."
---

Many useful tools need to look at your business system: reports, matching, alerts, backups. Giving them access feels risky, and sometimes it is.

The danger is rarely a bad tool. It is access that is wider than needed, shared, never reviewed and never removed. This guide shows how to connect a tool so that, if something goes wrong, the damage stays small.

## The rule: give only what the job needs

Give a tool the smallest access that does its job. For a reporting or monitoring tool, that means it can view the records it studies. It cannot create, change, send, cancel or delete anything.

You want two layers of protection:

1. **The tool promises to only look.** Good, but you are trusting its code.
2. **Your system only lets that user look.** Better. This still holds if the tool has a fault or is attacked.

## Step 1: Make a separate user for the tool

Never use a person's login. Create a new user just for the tool and name it clearly, for example "Monitoring, view only". Then:

- You can limit it without affecting a colleague.
- You can switch it off in one click without locking anyone out.
- Your logs show what the tool did, apart from what people did.
- Nobody has to share a password.

If a vendor asks for a person's username and password, treat that as a warning. Ask for a separate user, a key made for the tool, or an approval screen instead.

## Step 2: Make that user view-only

The steps differ by system. The idea is the same: say exactly what to ask for.

- **ERPNext:** make a role that can only read and run reports. Allow it only on the document types the tool needs. Give the role to the separate user, then make a key for that user.
- **Odoo:** make a separate user with the lowest access level for invoicing, sales and inventory that can still see the data. Give it no administrator rights.
- **Zoho Books and QuickBooks Online:** you approve the tool on a web page. Some systems let you choose view-only access. Others offer one combined choice. In that case the real limit is the user who approves. Sign in as a user who can only view or run reports, then approve. The tool can never do more than that user.

Read the permission screen every time. If it says "read and write" or "full access" and you only need a report, stop. Look for a narrower option.

## Step 3: Know what viewing still shows

View-only is not the same as harmless. A tool that can view can see customer names, supplier bank details, salaries and prices. So:

- **Limit what it can see,** not just what it can do. If the tool does not need payroll, do not give it payroll.
- **Ask what the tool keeps.** Does it store a copy of your data? For how long? Who at the vendor can see it?
- **Think about privacy.** You are normally responsible for your customers' and staff's personal data. Make sure you may share it, and that the vendor uses it only as you instruct.
- **Ask if you can delete** what it holds when you disconnect.

## Step 4: Protect the key

A key or token works like a password. Treat it like one.

- It is shown once. Put it in a password manager. Never send it by email or chat.
- Ask the vendor how they store it. It should be encrypted, never shown again and never written to logs.
- Where your system allows it, choose keys that expire.
- Replace keys regularly, and at once if you think one leaked. A good tool lets you swap a key without a gap.

## Step 5: Check the web address

Some tools ask you to type the web address of your own system. Check that it is an ordinary public address starting with https.

A well-made tool refuses private network addresses and bare internal names. This stops a connection being used to probe someone's internal network.

## Step 6: Test that it cannot change anything

Do not assume. Sign in as the separate user and try to create or edit something. Your system should refuse. If it does not, your permissions are too wide. Fix them before you connect any tool.

Then test what happens when access is removed. The tool should stop at once and tell you the connection needs attention. It should not fail silently.

## Step 7: Watch and review

- **Read the access log** of your system, if it has one, for the tool's user.
- **Set a reminder** to review connected tools every three months. Remove any you no longer use.
- **Write down why** each connection exists and who owns it.
- **Check the permissions again** after any upgrade of the tool.

## Step 8: Know how to cut access in minutes

Before you connect, find out how to disconnect:

- Switch off the separate user, or delete its key.
- Remove the tool in your system's list of connected apps.
- Make a new key. The old one stops working.

Practise once on a test user, so you are not hunting for the button during a problem. Access should stop at once. The tool should say "needs reconnecting".

## A checklist you can reuse

- [ ] A separate user or key, not a person's login.
- [ ] View-only, on only the records needed.
- [ ] Approved by a view-only user, where the system has no view-only option.
- [ ] Tested that changes are refused.
- [ ] Key stored safely, with a plan to replace it.
- [ ] Vendor's storage, deletion and staff-access rules understood.
- [ ] Way to cut access known and tested.
- [ ] Review date set.

## How Ziira does it

[Ziira Intelligence on your existing system](/intelligence/on-your-existing-system/) is built this way. It only reads. For Odoo it uses a short list of read calls, and refuses anything else before a request is made.

It asks for a separate, limited key, or an approval you can withdraw. It stores secrets encrypted and never shows them again. In production it refuses private network addresses.

QuickBooks Online has no view-only permission. So Ziira says so plainly and advises you to approve as a reports-only user.

The connections have been tested with sample replies, not yet with live accounts. Plan a first run on a demo company, not on your real books.

Details for each system: [ERPNext](/intelligence/on-your-existing-system/erpnext/), [Odoo](/intelligence/on-your-existing-system/odoo/), [Zoho Books](/intelligence/on-your-existing-system/zoho-books/) and [QuickBooks Online](/intelligence/on-your-existing-system/quickbooks-online/). See also the [security summary](/security-and-privacy/).

Whatever tool you use, the habit is the same. A separate user, view-only, tested, reviewed, and easy to switch off.
