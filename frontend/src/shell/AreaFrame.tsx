import { type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import { cx, type NavArea, type NavItem, type Placement, useTranslation } from "@/sdk";

const nameOf = (t: (k: string) => string, item: NavItem) => t(item.tab ?? item.label);

/** The Settings entries shown plainly, and the rarely used ones kept behind "Advanced". */
const ADVANCED = "advanced";
const splitSettings = (area: NavArea) => ({
  main: area.items.filter((i) => i.section !== ADVANCED),
  advanced: area.items.filter((i) => i.section === ADVANCED),
});

/** A phone-width stand-in for the Settings list: one select listing the entries, the rarely used ones under "Advanced". */
function SettingsSelect({ area, active }: { area: NavArea; active: NavItem }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { main, advanced } = splitSettings(area);
  const option = (i: NavItem) => <option key={i.to} value={i.to}>{nameOf(t, i)}</option>;
  return (
    <select aria-label={t(area.titleKey)} value={active.to} onChange={(e) => navigate(e.target.value)} className="h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm">
      {main.map(option)}
      {advanced.length > 0 && <optgroup label={t("nav.sections.advanced")}>{advanced.map(option)}</optgroup>}
    </select>
  );
}

/** Settings: a short plain list on the left (a select above the page on narrow screens), "Advanced" collapsed unless you are in it. */
function SettingsList({ area, head, children }: { area: NavArea; head: NavItem; children: ReactNode }) {
  const { t } = useTranslation();
  const { main, advanced } = splitSettings(area);
  const link = (i: NavItem) => (
    <li key={i.to}>
      <Link to={i.to} aria-current={i.to === head.to ? "page" : undefined}
        className={cx("block rounded-lg px-2.5 py-1.5 text-sm font-medium transition-colors", i.to === head.to ? "bg-brand-soft text-brand-strong" : "text-muted hover:bg-sunken hover:text-ink")}>
        {nameOf(t, i)}
      </Link>
    </li>
  );
  return (
    <div>
      <div className="grid gap-5 md:grid-cols-[13.5rem_minmax(0,1fr)] md:gap-8">
        <div className="no-print md:hidden"><SettingsSelect area={area} active={head} /></div>
        <nav aria-label={t(area.titleKey)} className="no-print hidden md:block">
          <div className="sticky top-20 space-y-3">
            <p className="px-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted">{t(area.titleKey)}</p>
            <ul className="space-y-0.5">{main.map(link)}</ul>
            {advanced.length > 0 && (
              <details key={advanced.some((i) => i.to === head.to) ? "in" : "out"} open={advanced.some((i) => i.to === head.to)} className="group">
                <summary className="cursor-pointer list-none rounded-lg px-2.5 py-1.5 text-sm font-medium text-muted hover:bg-sunken hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
                  {t("nav.sections.advanced")}<span aria-hidden className="ml-1 inline-block text-xs transition-transform group-open:rotate-90">›</span>
                </summary>
                <ul className="mt-0.5 space-y-0.5 border-l border-line pl-2">{advanced.map(link)}</ul>
              </details>
            )}
          </div>
        </nav>
        <div className="min-w-0">{children}</div>
      </div>
    </div>
  );
}

/** A small tab bar for the pages that share one sidebar entry (Quotations | Sales orders). */
function FamilyTabs({ pages, current }: { pages: NavItem[]; current: NavItem }) {
  const { t } = useTranslation();
  return (
    <nav aria-label={t(pages[0].tab ?? pages[0].label)} className="tab-strip no-print mb-4">
      {pages.map((p) => (
        <Link key={p.to} to={p.to} aria-current={p.to === current.to ? "page" : undefined}
          className={cx("-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors", p.to === current.to ? "border-brand text-ink" : "border-transparent text-muted hover:text-ink")}>
          {t(p.label)}
        </Link>
      ))}
    </nav>
  );
}

/**
 * Around the open page: Settings gets its grouped list on the left (a select on phones); an entry that covers several pages gets a small
 * tab bar above the page; every other page stands alone, its sidebar section already shows where it is.
 */
export function AreaFrame({ placement, children }: { placement: Placement | null; children: ReactNode }) {
  if (!placement) return <>{children}</>;
  const pages = placement.area.families[placement.head.to];
  if (placement.area.variant === "side") return <SettingsList area={placement.area} head={placement.head}>{pages ? <><FamilyTabs pages={pages} current={placement.item} />{children}</> : children}</SettingsList>;
  return pages ? <><FamilyTabs pages={pages} current={placement.item} />{children}</> : <>{children}</>;
}
