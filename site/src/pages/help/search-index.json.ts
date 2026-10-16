import type { APIRoute } from "astro";
import { helpGuides, helpGuideId, journeyOf } from "../../lib/help";
import { urlFor } from "../../lib/registry";
import { plain } from "../../lib/md";

/** The Help search index: one small record per guide (title, address, journey, words people may use). Built with the site. */
export const GET: APIRoute = () => {
  const rows = helpGuides.map((g) => ({
    t: g.h1,
    u: urlFor(helpGuideId(g.slug), "en"),
    j: journeyOf(g).title,
    k: [...(g.keywords ?? []), plain(g.description), ...g.steps.slice(0, 4).map((s) => plain(s.do))].join(" ").slice(0, 400),
  }));
  return new Response(JSON.stringify(rows), { headers: { "Content-Type": "application/json; charset=utf-8" } });
};
