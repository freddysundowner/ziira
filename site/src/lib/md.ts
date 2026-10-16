import type { Lang } from "../content/types";

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export type Resolve = (id: string, lang: Lang) => string;

/**
 * Tiny inline markup for content strings: **bold**, `code`, [text](@page-id) (internal, localised, resolved at build and
 * failing the build if the id does not exist) and [text](https://external). Everything else is HTML-escaped.
 */
export function inline(text: string, lang: Lang, resolve: Resolve): string {
  let out = esc(text);
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, label: string, target: string) => {
    if (target.startsWith("@")) return `<a href="${resolve(target.slice(1), lang)}">${label}</a>`;
    if (/^#[a-z0-9-]+$/.test(target)) return `<a href="${target}">${label}</a>`;
    if (/^https?:\/\//.test(target)) return `<a href="${target}" rel="noopener">${label}</a>`;
    throw new Error(`Bad link target "${target}" in: ${text.slice(0, 80)}`);
  });
  return out;
}

/** Plain text of inline markup (for meta descriptions and JSON-LD). */
export function plain(text: string): string {
  return text.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/\*\*/g, "").replace(/`/g, "");
}

/** Block Markdown for legal pages: ## headings, paragraphs, - lists. Raw HTML is escaped, never passed through. */
export function legalMarkdown(md: string, lang: Lang, resolve: Resolve): string {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  let list: string[] = [];
  let para: string[] = [];
  const flushList = () => { if (list.length) { out.push(`<ul>${list.map((l) => `<li>${inline(l, lang, resolve)}</li>`).join("")}</ul>`); list = []; } };
  const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(" "), lang, resolve)}</p>`); para = []; } };
  for (const line of lines) {
    if (/^##\s+/.test(line)) { flushList(); flushPara(); out.push(`<h2>${esc(line.replace(/^##\s+/, ""))}</h2>`); }
    else if (/^###\s+/.test(line)) { flushList(); flushPara(); out.push(`<h3>${esc(line.replace(/^###\s+/, ""))}</h3>`); }
    else if (/^\s*[-*]\s+/.test(line)) { flushPara(); list.push(line.replace(/^\s*[-*]\s+/, "")); }
    else if (line.trim() === "") { flushList(); flushPara(); }
    else { flushList(); para.push(line.trim()); }
  }
  flushList(); flushPara();
  return out.join("\n");
}
