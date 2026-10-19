import type { APIRoute } from "astro";
import { buildKnowledge } from "../lib/knowledge";

/** dist/assistant-knowledge.json: the floating assistant's source of truth (format in docs/marketing-site.md). */
export const GET: APIRoute = () =>
  new Response(JSON.stringify(buildKnowledge(), null, 1), { headers: { "Content-Type": "application/json; charset=utf-8" } });
