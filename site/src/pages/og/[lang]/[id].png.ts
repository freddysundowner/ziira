import type { APIRoute, GetStaticPaths } from "astro";
import satori from "satori";
import { Resvg } from "@resvg/resvg-js";
import fs from "node:fs";
import { createRequire } from "node:module";
import { allEntries, getEntry } from "../../../lib/registry";
import { siteConfig } from "../../../lib/siteConfig";

const require = createRequire(import.meta.url);
const fontDir = require.resolve("@fontsource/inter/package.json").replace("package.json", "files/");
const fonts = [
  { name: "Inter", data: fs.readFileSync(fontDir + "inter-latin-400-normal.woff"), weight: 400 as const, style: "normal" as const },
  { name: "Inter", data: fs.readFileSync(fontDir + "inter-latin-700-normal.woff"), weight: 700 as const, style: "normal" as const },
];

export const getStaticPaths = (() => allEntries().map((e) => ({ params: { lang: e.lang, id: e.id } }))) satisfies GetStaticPaths;

type N = { type: string; props: Record<string, unknown> };
const h = (type: string, props: Record<string, unknown>, ...children: unknown[]): N => ({ type, props: { ...props, children: children.length === 1 ? children[0] : children } });

export const GET: APIRoute = async ({ params }) => {
  const e = getEntry(params.lang as "en", params.id!)!;
  const title = e.def.title.replace(/\s*\(Template\)$/, "");
  const size = title.length <= 34 ? 76 : title.length <= 50 ? 64 : 54;
  const label = e.guideSlug ? "Guide" : e.def.eyebrow ?? e.def.short ?? "";
  const tree = h(
    "div",
    { style: { display: "flex", flexDirection: "column", justifyContent: "space-between", width: 1200, height: 630, padding: 72, background: "linear-gradient(135deg, #0b5550 0%, #0f766e 60%, #14a094 100%)", color: "#ffffff", fontFamily: "Inter" } },
    h("div", { style: { display: "flex", alignItems: "center" } },
      h("div", { style: { display: "flex", width: 56, height: 56, borderRadius: 14, background: "#ffffff", color: "#0f766e", alignItems: "center", justifyContent: "center", fontSize: 38, fontWeight: 700 } }, "Z"),
      h("div", { style: { marginLeft: 18, fontSize: 40, fontWeight: 700 } }, siteConfig.orgName)),
    h("div", { style: { display: "flex", flexDirection: "column" } },
      h("div", { style: { fontSize: 28, fontWeight: 400, opacity: 0.85, marginBottom: 20, textTransform: "uppercase", letterSpacing: 3 } }, label.slice(0, 60)),
      h("div", { style: { fontSize: size, fontWeight: 700, lineHeight: 1.1, letterSpacing: -1.5 } }, title)),
    h("div", { style: { display: "flex", fontSize: 26, opacity: 0.85 } }, "Simplify. Connect. Grow."),
  );
  const svg = await satori(tree as never, { width: 1200, height: 630, fonts });
  const png = new Resvg(svg, { fitTo: { mode: "width", value: 1200 } }).render().asPng();
  return new Response(new Uint8Array(png), { headers: { "Content-Type": "image/png" } });
};
