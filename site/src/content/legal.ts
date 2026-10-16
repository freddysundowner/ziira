import type { Lang } from "./types";

/** Built-in TEMPLATE texts (Markdown). Replaced by `siteConfig.legal.*Md` when the platform supplies reviewed text. */
export const legalTemplates: Record<"privacy" | "terms", string> = {
  privacy: `## 1. Who we are
[COMPANY LEGAL NAME], [REGISTRATION NUMBER], [REGISTERED ADDRESS] ("we"). Contact: [PRIVACY CONTACT].

## 2. What this policy covers
This policy covers personal data collected through this website: what you type into the contact form, and technical data your browser sends when it loads a page. It does not cover the Ziira product itself, where each business is responsible for its own customers' data.

## 3. What we collect
- **Contact form:** name, email address, optional business name and your message.
- **Server logs:** IP address, time, page requested and browser type. [CONFIRM RETENTION PERIOD]
- **Cookies and analytics:** [DESCRIBE, OR STATE THAT NONE ARE USED]

## 4. Why and on what basis
[LAWYER TO COMPLETE: purposes, legal basis for your jurisdiction.]

## 5. Who we share it with
[LIST PROCESSORS: form handling, email, hosting.]

## 6. How long we keep it
[RETENTION PERIODS]

## 7. Your rights
[RIGHTS UNDER APPLICABLE LAW AND HOW TO EXERCISE THEM]

## 8. Changes
[HOW CHANGES ARE COMMUNICATED] Last updated: [DATE].`,
  terms: `## 1. Agreement
By using this website you agree to these terms. [COMPANY LEGAL NAME] ("we") operates it.

## 2. Information, not advice
The content describes our software and is general information. It is not legal, tax, accounting or financial advice.

## 3. Product terms
Use of the Ziira product is governed by a separate agreement. [LINK OR STATE WHEN AVAILABLE]

## 4. Acceptable use
[LAWYER TO COMPLETE]

## 5. Intellectual property
[LAWYER TO COMPLETE]

## 6. Liability
[LAWYER TO COMPLETE, according to governing law]

## 7. Governing law
[JURISDICTION]

## 8. Contact
[CONTACT DETAILS] Last updated: [DATE].`,
};

export const legalBanner: Record<Lang, { title: string; text: string }> = {
  en: { title: "This page is a template", text: "It contains bracketed placeholders and is not legal advice. A lawyer must review and complete it before it is relied on. Until then this page is marked noindex." },
};
