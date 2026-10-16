import type { APIRoute } from "astro";
import { guides } from "../../lib/guides";
import { absUrl, siteConfig } from "../../lib/siteConfig";

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export const GET: APIRoute = () => {
  const updated = guides.reduce((m, g) => (g.updated > m ? g.updated : m), "1970-01-01");
  const entries = guides
    .map((g) => {
      const url = absUrl(`/guides/${g.slug}/`);
      return `  <entry>
    <title>${esc(g.h1)}</title>
    <link href="${esc(url)}"/>
    <id>${esc(url)}</id>
    <published>${g.date}T00:00:00Z</published>
    <updated>${g.updated}T00:00:00Z</updated>
    <author><name>${esc(siteConfig.orgName)}</name></author>
    <summary>${esc(g.description)}</summary>
  </entry>`;
    })
    .join("\n");
  const xml = `<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="en">
  <title>${esc(siteConfig.orgName)} guides</title>
  <link href="${esc(absUrl("/guides/feed.xml"))}" rel="self"/>
  <link href="${esc(absUrl("/guides/"))}"/>
  <id>${esc(absUrl("/guides/"))}</id>
  <updated>${updated}T00:00:00Z</updated>
${entries}
</feed>
`;
  return new Response(xml, { headers: { "Content-Type": "application/atom+xml; charset=utf-8" } });
};
