import type { APIRoute } from "astro";
import { allEntries } from "../lib/registry";
import { absUrl } from "../lib/siteConfig";

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export const GET: APIRoute = () => {
  const rows = allEntries()
    .filter((e) => e.indexable)
    .sort((a, b) => a.path.localeCompare(b.path))
    .map((e) => {
      return `  <url>\n    <loc>${esc(absUrl(e.path))}</loc>\n    <lastmod>${e.lastmod}</lastmod>\n  </url>`;
    });
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n${rows.join("\n")}\n</urlset>\n`;
  return new Response(xml, { headers: { "Content-Type": "application/xml; charset=utf-8" } });
};
