import type { HelpGuide } from "../content/help/types";
import { plain } from "./md";
import { absUrl } from "./siteConfig";

const shorten = (t: string, max = 90) => {
  const one = t.replace(/\s+/g, " ").trim();
  if (one.length <= max) return one;
  return one.slice(0, max).replace(/\s+\S*$/, "") + "…";
};

/** HowTo structured data for one guide: one HowToStep per numbered step shown on the page. No images, ratings or prices are invented. */
export function howToNode(g: HelpGuide, path: string): Record<string, unknown> {
  const url = absUrl(path);
  return {
    "@type": "HowTo",
    "@id": `${url}#howto`,
    name: g.h1,
    description: g.description,
    inLanguage: "en",
    totalTime: `PT${g.minutes}M`,
    ...(g.need.length ? { supply: g.need.map((n) => ({ "@type": "HowToSupply", name: plain(n) })) } : {}),
    step: g.steps.map((s, i) => ({
      "@type": "HowToStep",
      position: i + 1,
      name: shorten(plain(s.do)),
      text: [plain(s.do), s.result ? `You should see: ${plain(s.result)}` : ""].filter(Boolean).join(" "),
      url: `${url}#step-${i + 1}`,
    })),
  };
}
