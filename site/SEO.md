# SEO plan for the Ziira marketing site

SEO is the reason this site is **static pre-rendered HTML** (the product web app is a client-rendered SPA, which search engines
handle poorly). This file is the plan the pages were built from: audiences, one primary search intent per page (so pages do not
compete with each other), the technical checklist and how each item is enforced.

**Honesty note.** The keywords below are hypotheses from the product's audiences, not measured search volumes. After launch,
verify them in Google Search Console (queries, impressions, click-through) and adjust titles and headings. No volumes are claimed.

## Audiences

1. Owners and managers of small and medium retail, distribution and multi-branch businesses (shops, hardware, agrovets, pharmacies, wholesalers).
2. People who already run an ERP or accounting package (Odoo, ERPNext, Zoho Books, QuickBooks Online) and worry about leaks or fraud.
3. Accountants and finance managers (reconciliation, month-end, controls).
4. Owners who want alerts on their phone (WhatsApp) rather than reports at a desk.

## Intent map: one primary intent per page

| Page (English URL) | Primary intent (what a searcher wants) | Secondary phrases | Type |
|---|---|---|---|
| `/` | Ziira brand; ERP for SMEs with fraud and leak detection | ERP for small business, business intelligence alerts | Navigational / commercial |
| `/product/` | Business system / ERP for shops and distributors | ERP for SMEs, multi-branch ERP | Commercial |
| `/product/pos-and-till/` | POS software with offline selling | POS with till control, POS that works without internet | Commercial |
| `/product/inventory-and-branches/` | Multi-branch inventory management software | stock transfers between branches, stock counts | Commercial |
| `/product/purchasing-and-suppliers/` | Purchase order to supplier bill, three-way match | supplier management software | Commercial |
| `/product/accounting-and-finance/` | Accounting software that posts automatically | automatic general ledger for retail | Commercial |
| `/product/people-and-payroll/` | Payroll software with configurable statutory rules | payroll for SMEs, payroll rules by country | Commercial |
| `/product/customers-and-credit/` | Customer credit and receivables software | customer statements, credit limits | Commercial |
| `/product/payments-and-reconciliation/` | Payment reconciliation: mobile money, cash and bank to sales | daily branch close | Commercial |
| `/intelligence/complete-guide/` | Full reference: every check, the AI helper, action levels (optional detail behind the step-by-step page) | what does it check, AI helper, action levels | Informational |
| `/intelligence/how-it-works/` | Fraud and leak detection for my business: how the daily check works (the one page for the Intelligence intent; six steps, HowTo data; `/intelligence/` redirects here) | business intelligence alerts, daily owner alerts, how it works | Commercial / informational |
| `/intelligence/on-your-existing-system/` | Add fraud detection to the ERP I already use | monitor my ERP for fraud, read-only | Commercial |
| `.../erpnext/` | ERPNext fraud and leak detection | monitor ERPNext | Commercial (long tail) |
| `.../odoo/` | Odoo fraud and leak detection | Odoo API read-only | Commercial (long tail) |
| `.../zoho-books/` | Zoho Books fraud detection | Zoho Books read-only access | Commercial (long tail) |
| `.../quickbooks-online/` | QuickBooks Online fraud detection | QuickBooks read-only | Commercial (long tail) |
| `.../bank-statements/` | Reconcile bank statements to sales | bank statement fraud checks | Commercial |
| `.../mobile-money-statements/` | Reconcile mobile-money statements to sales | M-Pesa statement reconciliation | Commercial |
| `.../csv-excel-pdf/` | Use sales and stock exports (CSV, Excel, PDF) for checks | no-API systems | Commercial |
| `/ai/` | AI for business: ask questions of your business data, AI daily checks, AI that shows proof | business AI assistant, AI accounting and stock checks | Commercial |
| `/solutions/every-business/`, salons, garages, clinics, gyms, consultants | Business software for each kind of business (one intent each) | salon software, garage and body shop software with insurer claims, clinic billing software, gym membership software | Commercial |
| `/solutions/` and three children | ERP/POS for a retailer; for a distributor; for a multi-branch owner | | Commercial |
| `/integrations/` and children | What does Ziira connect to (WhatsApp alerts, M-Pesa, ERPs, statements, API); WhatsApp business alerts; M-Pesa integration; ERP API and webhooks | | Commercial / technical |
| `/security-and-privacy/` | Is it safe; how is my data protected | read-only ERP access, data protection | Trust |
| `/pricing/`, `/get-started/` | Price; sign up / contact | | Transactional |
| `/about/` | Who is behind it | | Trust |
| `/guides/` and nine articles | Long-tail how-to questions (see below) | | Informational |
| `/help/` and about fifty guides | How do I use Ziira to ...? (make a sale, receive goods, run payroll): task intents, one per guide, HowTo structured data | | Informational / support |
| `/glossary/` | Definitions (ERP, void, shrinkage, three-way match...) | | Informational |

### Guides: one long-tail question each

| Guide | Question it answers |
|---|---|
| `cashier-voids-discount-abuse` | How do I spot cashier voids and discount abuse? |
| `reconcile-mobile-money` | How do I reconcile mobile-money statements to sales? |
| `daily-owner-brief` | What should a daily owner brief contain? |
| `stock-shrinkage` | How do I detect stock shrinkage? |
| `month-end-close` | What is a month-end close checklist for a small business? |
| `choose-pos-multi-branch` | How do I choose POS software for a multi-branch shop? |
| `read-only-access` | How do I connect my ERP to a tool safely (read-only)? |
| `offline-pos` | What happens when the till loses internet? |
| `separation-of-duties` | How do small businesses separate duties? |

**No cannibalisation rules.** A capability page describes the capability; the matching guide teaches the generic practice and links to
the capability page. Source pages (ERPNext, Odoo...) target the vendor name; the hub targets the generic "on your existing system" intent.
When adding a page, add a row here first and make sure its primary intent is not already taken.

## Technical checklist and where it is enforced

| Item | How it is done | Enforced by (`npm run seo:check`) |
|---|---|---|
| Unique `<title>` (<= 60 chars) and meta description (50-160) | written per page in `src/content/` | `title-*`, `description-*` |
| Canonical URL, self-referencing | `src/layouts/Base.astro` from `PUBLIC_SITE_URL` | `canonical-*` |
| robots meta; `noindex` only where allowed | legal templates are noindex until `PUBLIC_LEGAL_REVIEWED=true`; 404 | `noindex-unexpected` (allow-list `scripts/noindex-allowlist.json`) |
| One H1, no skipped heading levels | templates | `h1-count`, `heading-order` |
| Open Graph and Twitter cards; a generated 1200x630 image per page | `src/pages/og/[lang]/[id].png.ts` (satori + resvg at build time) | `og-*` |
| JSON-LD: Organization, WebSite (no SearchAction: there is no search), WebPage, BreadcrumbList, SoftwareApplication (BusinessApplication, no offers or ratings), FAQPage, BlogPosting | `src/lib/schema.ts` | `jsonld-*` (parse, types, no fabricated rating/offers, FAQ matches visible FAQ) |
| `sitemap.xml` with `lastmod` (hreflang alternates only if a second language is added) | `src/pages/sitemap.xml.ts` | `sitemap-*` |
| `robots.txt` allows all and names the sitemap | `src/pages/robots.txt.ts` | `robots-*` |
| hreflang: none today (English only); if a language is added, `x-default`, reciprocal pairs | `src/lib/seo.ts` | `hreflang-*` (inert until alternates exist) |
| Clean URLs, trailing slash always | `astro.config.mjs` (`trailingSlash: "always"`, directory output) | `link-trailing-slash` |
| 301 map for future moves | `redirects.json` -> `dist/_redirects` | (file written at build) |
| Internal links with descriptive anchors; breadcrumbs; no orphans | footers list every page; hubs list their children | `link-*`, `orphan-page` |
| Images: AVIF/WebP, width and height, lazy except the hero, alt text | `src/components/Screenshot.astro` | `img-*`, `budget-image` |
| Performance budgets (HTML, CSS, JS, page images) | no framework JS, inline CSS, system fonts | `budget-*` |
| Accessibility: landmarks, skip link, focus styles, contrast, reduced motion | `global.css`, templates | `landmark-missing`, `skip-link-missing`; `npm run a11y` (axe) |
| Atom feed for guides, `llms.txt`, web manifest, favicons | `src/pages/` | `file-missing` |
| Security headers | `public/_headers` | `file-missing` |
| Real origin set for production | `PUBLIC_SITE_URL` | `site-url` (with `--production` or `ZIIRA_SITE_ENV=production`); the build also warns loudly (or fails with `SITE_STRICT=1`) |

## After launch (not done here)

1. Verify the domain in Google Search Console and Bing Webmaster Tools; submit `/sitemap.xml`.
2. Watch the Page indexing report for "Crawled, currently not indexed" on thin pages; merge or deepen them.
3. Use Search Console queries to rename titles and H1s to the words people use.
4. Link from the product app's footer, the GitHub repository and any directories you list in.
5. Re-run Lighthouse on the production URL (real CDN, real compression); Core Web Vitals field data appears after a few weeks.

## Design refresh (layout only)

The layout, navigation labels and hero wording changed (header menus: What Ziira does / Who it is for / How it works / Pricing / Help). URLs, titles, descriptions, structured data and the intent map above are unchanged; the H1 of `/`, `/product/`, `/intelligence/`, `/solutions/`, `/integrations/`, `/pricing/` and `/get-started/` was made more specific. Re-check them in Search Console after launch like the rest.

## Straight-to-the-point navigation (2026-10-16)

Owner decision: no in-between pages. The old Intelligence hub `/intelligence/` was removed and 301-redirects to `/intelligence/how-it-works/` (`redirects.json`, written to `dist/_redirects`); the menu item "Daily check: catch mistakes and losses", the home page, the footer and the 404 page link straight to it. `/intelligence/how-it-works/` carries the Intelligence intent, HowTo structured data (six steps), the breadcrumb Home > How Intelligence works, and links to the complete guide as an optional full reference. Menu entries under "What Ziira does" and "Who it is for" point at the capability and solution pages; the top label "Who it is for" opens Retail directly. Articles, the complete guide and the Help centre follow the plain-language rules in `docs/marketing-site.md` ("Writing style"), enforced by `tests/style.test.ts`.
