import type { APIRoute } from "astro";
import { entriesFor } from "../lib/registry";
import { absUrl, siteConfig } from "../lib/siteConfig";

/** llms.txt: a plain description of the site for AI crawlers, generated from the same registry as the sitemap. */
export const GET: APIRoute = () => {
  const en = entriesFor("en").filter((e) => e.indexable);
  const group = (title: string, pick: (id: string) => boolean) => {
    const rows = en.filter((e) => pick(e.id) && !e.guideSlug).map((e) => `- [${e.def.short ?? e.def.title}](${absUrl(e.path)}): ${e.def.description}`);
    return rows.length ? `## ${title}\n\n${rows.join("\n")}\n` : "";
  };
  const guideRows = en.filter((e) => e.guideSlug).map((e) => `- [${e.def.h1}](${absUrl(e.path)}): ${e.def.description}`);
  const body = `# ${siteConfig.orgName}

> ${siteConfig.orgName} is an AI-first business system for every kind of business, from one till to many branches and companies: selling, stock, buying, customers, accounting, payroll, payments, bookings, jobs, insurer claims, memberships and projects billed by time. Ziira AI checks business data every day, answers questions in plain words with the proof beside the answer, and prepares next steps for a person to approve. It never moves money. Intelligence can also watch a system you already use (Odoo, ERPNext, Zoho Books, QuickBooks Online, bank and mobile-money statements, CSV/Excel/PDF exports) without changing it.

Notes for readers and models: prices, ratings, customers and certifications are stated only where published on the page.

${group("Product and Ziira AI", (id) => id === "product" || id === "ai" || id.startsWith("core-") || id === "intelligence-complete" || id === "intelligence-how")}
${group("Intelligence on your existing system", (id) => id === "intelligence-existing" || id.startsWith("intelligence-source-"))}
${group("Solutions and integrations", (id) => id.startsWith("solutions") || id.startsWith("integrations"))}
${group("Help centre: step-by-step guides for using Ziira", (id) => id === "help" || id.startsWith("help-") || id.startsWith("helpj-"))}
${group("Company, trust and pricing", (id) => ["about", "security", "pricing", "get-started", "glossary"].includes(id))}
## Guides

${guideRows.join("\n")}
`;
  return new Response(body.replace(/\n{3,}/g, "\n\n"), { headers: { "Content-Type": "text/plain; charset=utf-8" } });
};
