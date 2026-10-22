import { ArrowRight, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  areaMembers, buildNavigation, EmptyState, iconFor, Input, orderedGroups, PageHeader, profileFor, SETTINGS_HOME, SIDEBAR, useAccess, useActiveModules, useEdition, useSession, useTranslation,
  type NavItem,
} from "@/sdk";

/** The sentence under a group's name: by page, else by the heading the page is listed under. */
const blurbKey = (head: NavItem) => `nav.settings.d.${head.section === "platform" ? "plan" : head.section || "business"}`;

/**
 * The first page of Settings: a search box ("Find a setting") and one calm card per group, each saying in a line what is inside.
 * It is built from the same menu the Settings list uses, so a business sees only the groups it has (units that are off, pages the person
 * may not open and, for a business with no counter, the till settings are absent).
 */
export default function SettingsHomePage() {
  const { t } = useTranslation();
  const modules = useActiveModules();
  const access = useAccess();
  const { edition } = useEdition();
  const { enabledUnits } = useSession();
  const [q, setQ] = useState("");

  const area = useMemo(
    () => buildNavigation(modules, access, orderedGroups(edition), SIDEBAR[profileFor(edition?.id, enabledUnits)]).areas.find((a) => a.id === "settings"),
    [modules, access, edition, enabledUnits],
  );
  const name = (i: NavItem) => t(i.tab ?? i.label);
  const heads = (area?.items ?? []).filter((i) => i.to !== SETTINGS_HOME);
  const main = heads.filter((i) => i.section !== "advanced");
  const advanced = heads.filter((i) => i.section === "advanced");

  // A card per group: Advanced is one card that opens its first page and names the others.
  const groups = [
    ...main.map((head) => ({ head, title: name(head), blurb: t(blurbKey(head)), pages: area ? (area.families[head.to] ?? [head]) : [head] })),
    ...(advanced.length ? [{ head: advanced[0], title: t("nav.settings.advanced"), blurb: t("nav.settings.d.advanced"), pages: advanced }] : []),
  ];

  const needle = q.trim().toLowerCase();
  const hits = !needle || !area ? [] : areaMembers(area).filter((i) => i.to !== SETTINGS_HOME).filter((i) => [t(i.label), name(i), i.keywords ? t(i.keywords) : ""].join(" ").toLowerCase().includes(needle));
  const groupOf = (page: NavItem) => groups.find((g) => g.pages.some((p) => p.to === page.to))?.title ?? "";

  return (
    <>
      <PageHeader title={t("nav.settings.title")} description={t("nav.settings.intro")} />
      <div className="relative mb-6 max-w-md">
        <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
        <Input type="search" aria-label={t("nav.settings.find")} placeholder={t("nav.settings.findPlaceholder")} value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" />
      </div>

      {needle ? (
        hits.length === 0 ? <EmptyState title={t("nav.settings.noMatch", { q: q.trim() })} /> : (
          <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface" aria-live="polite">
            {hits.map((p) => (
              <li key={p.to}>
                <Link to={p.to} className="flex items-center justify-between gap-3 px-4 py-3 text-sm hover:bg-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand">
                  <span className="font-medium text-ink">{t(p.label)}</span>
                  <span className="text-xs text-muted">{t("nav.settings.in", { group: groupOf(p) })}</span>
                </Link>
              </li>
            ))}
          </ul>
        )
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {groups.map(({ head, title, blurb }) => {
            const Icon = iconFor(head.icon);
            return (
              <li key={head.to} className="min-w-0">
                <Link to={head.to} className="group flex h-full min-w-0 flex-col gap-2 rounded-xl border border-line bg-surface p-4 transition-colors hover:border-brand hover:bg-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
                  <span className="flex min-w-0 items-center gap-2.5">
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand-strong"><Icon className="h-4 w-4" aria-hidden /></span>
                    <span className="min-w-0 text-sm font-semibold text-ink [overflow-wrap:anywhere]">{title}</span>
                    <ArrowRight aria-hidden className="ml-auto h-4 w-4 shrink-0 text-muted transition-transform group-hover:translate-x-0.5" />
                  </span>
                  <span className="text-sm text-muted [overflow-wrap:anywhere]">{blurb}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
