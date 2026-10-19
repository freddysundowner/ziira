import type { Lang } from "../content/types";
import { absUrl, siteConfig } from "./siteConfig";
import { type Entry } from "./registry";
import { ogPath } from "./seo";
import { plain } from "./md";

const orgId = () => absUrl("/#organization");
const siteId = () => absUrl("/#website");

export function organizationNode() {
  const c = siteConfig;
  const node: Record<string, unknown> = {
    "@type": "Organization",
    "@id": orgId(),
    name: c.orgName,
    url: absUrl("/"),
    logo: absUrl(c.company.logo?.path ?? "/icon-512.png"),
  };
  if (c.legalName) node.legalName = c.legalName;
  if (c.social.length) node.sameAs = c.social;
  const points = [
    c.contact.email && { contactType: "customer support", email: c.contact.email },
    c.contact.salesEmail && { contactType: "sales", email: c.contact.salesEmail },
    ...c.contact.phones.map((telephone) => ({ contactType: "customer support", telephone })),
  ].filter(Boolean) as Record<string, string>[];
  if (points.length) node.contactPoint = points.map((p) => ({ "@type": "ContactPoint", ...p, availableLanguage: ["English"] }));
  if (c.contact.address) node.address = { "@type": "PostalAddress", streetAddress: c.contact.address.replace(/\s*\n\s*/g, ", ") };
  if (c.company.taxId) node.taxID = c.company.taxId;
  return node;
}

export function websiteNode(lang: Lang) {
  // No SearchAction: the site has no search.
  return { "@type": "WebSite", "@id": siteId(), url: absUrl("/"), name: siteConfig.orgName, inLanguage: lang, publisher: { "@id": orgId() } };
}

function softwareNode(name: string, description: string, url: string, lang: Lang) {
  // No offers, ratings or reviews: none exist to state truthfully.
  return {
    "@type": "SoftwareApplication",
    "@id": `${url}#software`,
    name,
    description,
    url,
    applicationCategory: "BusinessApplication",
    operatingSystem: "Web browser",
    inLanguage: lang,
    featureList: SOFTWARE_TEXT.features,
    publisher: { "@id": orgId() },
  };
}

export interface GraphInput {
  entry: Entry;
  crumbs: { name: string; path: string }[];
  faq?: { q: string; a: string }[];
  article?: { published: string; modified: string; words: number };
  /** A long-form explainer (the complete guide): emitted as TechArticle. */
  tech?: { published: string; modified: string; words: number; about: string[] };
  software?: boolean;
  /** An ItemList of pages (the Integrations page): name and absolute-able path of each item. */
  itemList?: { name: string; path: string }[];
}

const SOFTWARE_TEXT = {
  name: "Ziira",
  en: "AI-first business system for every kind of business: selling, stock, buying, customers, accounting, payroll, bookings, jobs, claims, memberships and projects, with AI that checks the business every day, answers in plain words and prepares next steps for approval.",
  features: ["Ziira AI: ask in plain words, answers with proof, suggestions you approve", "Daily checks, alerts and a daily summary", "Point of sale with offline selling", "Stock by branch", "Purchasing and supplier bills", "Customer credit", "Accounting that posts itself", "Payroll", "Payment matching", "Appointments and bookings", "Jobs and repairs", "Insurer and payer claims", "Memberships and recurring invoices", "Projects and time billing", "Works on top of a system you already use, read only"],
};

export function graphFor(input: GraphInput, softwareUrl: () => string): Record<string, unknown> {
  const { entry, crumbs, faq, article, tech, software, itemList } = input;
  const url = absUrl(entry.path);
  const graph: Record<string, unknown>[] = [organizationNode(), websiteNode(entry.lang)];

  graph.push({
    "@type": entry.def.kind === "guides" ? "CollectionPage" : "WebPage",
    "@id": `${url}#webpage`,
    url,
    name: entry.def.title,
    description: entry.def.description,
    inLanguage: entry.lang,
    isPartOf: { "@id": siteId() },
    primaryImageOfPage: { "@type": "ImageObject", url: absUrl(ogPath(entry)), width: 1200, height: 630 },
    ...(crumbs.length > 1 ? { breadcrumb: { "@id": `${url}#breadcrumb` } } : {}),
  });

  if (crumbs.length > 1) {
    graph.push({
      "@type": "BreadcrumbList",
      "@id": `${url}#breadcrumb`,
      itemListElement: crumbs.map((c, i) => ({ "@type": "ListItem", position: i + 1, name: c.name, item: absUrl(c.path) })),
    });
  }
  if (software) graph.push(softwareNode(SOFTWARE_TEXT.name, SOFTWARE_TEXT.en, absUrl(softwareUrl()), entry.lang));
  if (itemList?.length) {
    graph.push({
      "@type": "ItemList",
      "@id": `${url}#list`,
      name: entry.def.h1,
      itemListElement: itemList.map((it, n) => ({ "@type": "ListItem", position: n + 1, name: it.name, url: absUrl(it.path) })),
    });
  }
  if (faq?.length) {
    graph.push({
      "@type": "FAQPage",
      "@id": `${url}#faq`,
      mainEntity: faq.map((f) => ({ "@type": "Question", name: plain(f.q), acceptedAnswer: { "@type": "Answer", text: plain(f.a) } })),
    });
  }
  if (article) {
    graph.push({
      "@type": "BlogPosting",
      "@id": `${url}#article`,
      headline: entry.def.h1,
      description: entry.def.description,
      datePublished: article.published,
      dateModified: article.modified,
      inLanguage: entry.lang,
      wordCount: article.words,
      author: { "@id": orgId() },
      publisher: { "@id": orgId() },
      image: absUrl(ogPath(entry)),
      mainEntityOfPage: { "@id": `${url}#webpage` },
    });
  }
  if (tech) {
    graph.push({
      "@type": "TechArticle",
      "@id": `${url}#article`,
      headline: entry.def.h1,
      description: entry.def.description,
      datePublished: tech.published,
      dateModified: tech.modified,
      inLanguage: entry.lang,
      wordCount: tech.words,
      about: tech.about.map((name) => ({ "@type": "Thing", name })),
      author: { "@id": orgId() },
      publisher: { "@id": orgId() },
      image: absUrl(ogPath(entry)),
      mainEntityOfPage: { "@id": `${url}#webpage` },
    });
  }
  return { "@context": "https://schema.org", "@graph": graph };
}
