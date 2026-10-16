import type { APIRoute } from "astro";
import { absUrl } from "../lib/siteConfig";

export const GET: APIRoute = () =>
  new Response(`User-agent: *\nAllow: /\n\nSitemap: ${absUrl("/sitemap.xml")}\n`, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
