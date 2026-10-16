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

> ${siteConfig.orgName} is a business system for small and medium retail and distribution businesses: selling, stock, buying, customers on credit, books, payments and payroll. Its Intelligence part checks business data every day and alerts owners to money and stock that do not add up. Intelligence can also watch a system you already use (Odoo, ERPNext, Zoho Books, QuickBooks Online, bank and mobile-money statements, CSV/Excel/PDF exports) without changing it.

Notes for readers and models: integrations with outside services are described with their honest status (several have not yet been run against live services). No prices, ratings, customers or certifications are stated unless published on the page.

${group("Product and Intelligence", (id) => id === "product" || id.startsWith("core-") || id === "intelligence-complete" || id === "intelligence-how")}
${group("Intelligence on your existing system", (id) => id === "intelligence-existing" || id.startsWith("intelligence-source-"))}
${group("Solutions and integrations", (id) => id.startsWith("solutions") || id.startsWith("integrations"))}
${group("Help centre: step-by-step guides for using Ziira", (id) => id === "help" || id.startsWith("help-") || id.startsWith("helpj-"))}
${group("Company, trust and pricing", (id) => ["about", "security", "pricing", "get-started", "glossary"].includes(id))}
## Guides

${guideRows.join("\n")}
`;
  return new Response(body.replace(/\n{3,}/g, "\n\n"), { headers: { "Content-Type": "text/plain; charset=utf-8" } });
};
