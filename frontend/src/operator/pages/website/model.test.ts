import { describe, expect, it } from "vitest";

import { changes, countTone, fromLocalInput, groupIssues, imageSnippet, missingLegal, quickProblem, quickProblems, slugFrom, socialUrl, toForm, toLocalInput, toRaw, whatsappLink } from "./model";

describe("turning server values into a form and back", () => {
  const values = {
    company_legal_name: "Acme Ltd", tagline: { en: "Hello" }, phones: ["+44 20 7946 0958", "+254 700 123 456"], locales: ["en", "sw"],
    analytics_enabled: true, banner_starts_at: "2026-12-01T09:00:00+00:00",
  };

  it("shows text, one box per language, one phone per line and switches", () => {
    const form = toForm(["company_legal_name", "tagline", "phones", "locales", "analytics_enabled", "banner_active", "sales_email"], values);
    expect(form.company_legal_name).toBe("Acme Ltd");
    expect(form.tagline).toEqual({ en: "Hello", sw: "" });
    expect(form.phones).toBe("+44 20 7946 0958\n+254 700 123 456");
    expect(form.locales).toBe("en, sw");
    expect(form.analytics_enabled).toBe(true);
    expect(form.banner_active).toBe(false);
    expect(form.sales_email).toBe("");
  });

  it("sends nothing for an untouched form and only the changed settings otherwise", () => {
    const keys = ["company_legal_name", "tagline", "phones", "analytics_enabled", "sales_email"];
    const form = toForm(keys, values);
    expect(changes(keys, form, values)).toEqual({});
    form.company_legal_name = " New Name ";
    form.sales_email = "sales@acme.test";
    (form.tagline as Record<string, string>).sw = "Habari";
    form.phones = "+44 20 7946 0958";
    expect(changes(keys, form, values)).toEqual({
      company_legal_name: "New Name", sales_email: "sales@acme.test", tagline: { en: "Hello", sw: "Habari" }, phones: ["+44 20 7946 0958"],
    });
  });

  it("clears a setting by emptying it", () => {
    const form = toForm(["company_legal_name", "tagline", "analytics_enabled"], values);
    form.company_legal_name = "  ";
    form.tagline = { en: "", sw: "" };
    form.analytics_enabled = false;
    expect(changes(["company_legal_name", "tagline", "analytics_enabled"], form, values)).toEqual({ company_legal_name: null, tagline: null, analytics_enabled: null });
  });

  it("splits phones on lines or commas and languages on commas or spaces", () => {
    expect(toRaw("phones", "+1 555 0100,\n +44 20 7946 0958 ")).toEqual(["+1 555 0100", "+44 20 7946 0958"]);
    expect(toRaw("locales", "en,  sw pt-BR")).toEqual(["en", "sw", "pt-BR"]);
  });

  it("keeps a moment exact through the browser's local-time box", () => {
    const iso = "2026-12-01T09:30:00.000Z";
    expect(fromLocalInput(toLocalInput(iso))).toBe(iso);
    expect(toLocalInput("nonsense")).toBe("");
    expect(fromLocalInput("nonsense")).toBeNull();
  });
});

describe("the quick checks (the server decides, these only save a round trip)", () => {
  it("accepts any country's international numbers and refuses local forms", () => {
    for (const ok of ["+44 20 7946 0958", "+254 700 123 456", "+1 (555) 010-0100", "+81 3-1234-5678"]) expect(quickProblem("whatsapp_number", ok)).toBeNull();
    for (const bad of ["0700 123 456", "+12", "call me", "+1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6"]) expect(quickProblem("whatsapp_number", bad)).toBe("phone");
    expect(quickProblem("phones", "+44 20 7946 0958\n0700 1")).toBe("phone");
  });

  it("checks emails, addresses and handles", () => {
    expect(quickProblem("support_email", "help@acme.test")).toBeNull();
    expect(quickProblem("support_email", "help@acme")).toBe("email");
    expect(quickProblem("app_url", "https://app.acme.test")).toBeNull();
    expect(quickProblem("app_url", "javascript:alert(1)")).toBe("url");
    expect(quickProblem("app_url", "https://user:pw@acme.test")).toBe("url");
    expect(quickProblem("banner_link", "/pricing")).toBeNull();
    expect(quickProblem("banner_link", "//evil.test")).toBe("url");
    expect(quickProblem("contact_form_target", "forms@acme.test")).toBeNull();
    expect(quickProblem("social_x", "@acme")).toBeNull();
    expect(quickProblem("social_linkedin", "company-name")).toBeNull();
    expect(quickProblem("social_github", "has space")).toBe("handle");
    expect(quickProblem("locales", "en, sw")).toBeNull();
    expect(quickProblem("locales", "English")).toBe("locales");
    expect(quickProblem("seo_title_template", { en: "no token" })).toBe("token");
    expect(quickProblem("seo_title_template", { en: "{title} | Acme", sw: "" })).toBeNull();
    expect(quickProblem("company_legal_name", "x".repeat(300), 160)).toBe("tooLong");
  });

  it("collects the problems of a whole form", () => {
    expect(quickProblems(["support_email", "sales_email"], { support_email: "bad", sales_email: "" })).toEqual({ support_email: "email" });
  });

  it("builds the links a handle stands for", () => {
    expect(socialUrl("social_x", "@acme")).toBe("https://x.com/acme");
    expect(socialUrl("social_github", "https://github.com/acme")).toBe("https://github.com/acme");
    expect(socialUrl("social_x", "")).toBeNull();
    expect(whatsappLink("+254 700 123 456")).toBe("https://wa.me/254700123456");
    expect(whatsappLink("0700")).toBeNull();
  });
});

describe("pages", () => {
  it("makes web-address parts from titles", () => {
    expect(slugFrom("Data Processing Terms!")).toBe("data-processing-terms");
    expect(slugFrom("  Sera ya faragha  ")).toBe("sera-ya-faragha");
    expect(slugFrom("Café & Bar")).toBe("cafe-bar");
  });

  it("lists the legal pages a language is still missing", () => {
    const pages = [{ slug: "privacy", locale: "en", kind: "legal" }, { slug: "terms", locale: "en", kind: "legal" }, { slug: "privacy", locale: "sw", kind: "legal" }];
    expect(missingLegal(pages, "en")).toEqual(["cookies", "refunds", "acceptable-use", "data-processing"]);
    expect(missingLegal(pages, "sw")).toHaveLength(5);
  });

  it("groups report lines by kind and writes picture lines", () => {
    expect(groupIssues([{ code: "a", n: 1 }, { code: "b", n: 2 }, { code: "a", n: 3 }]).map(([c, l]) => [c, l.length])).toEqual([["a", 2], ["b", 1]]);
    expect(imageSnippet("0123456789abcdef", "Our [logo]")).toBe("![Our logo](asset:0123456789abcdef)");
    expect(countTone(61, 60)).toBe("warn");
    expect(countTone(60, 60)).toBe("muted");
  });
});
