import { type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import { cx, itemsOfSection, type NavArea, type NavItem, type Placement, useTranslation } from "@/sdk";

const nameOf = (t: (k: string) => string, item: NavItem) => t(item.tab ?? item.label);

/** A phone-width stand-in for the Settings list: one select listing the pages by heading. */
function SettingsSelect({ area, active }: { area: NavArea; active: NavItem }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const option = (i: NavItem) => <option key={i.to} value={i.to}>{nameOf(t, i)}</option>;
  return (
    <select aria-label={t(area.titleKey)} value={active.to} onChange={(e) => navigate(e.target.value)} className="h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm">
      {area.sections.map((s) => (s ? <optgroup key={s} label={t(`nav.sections.${s}`, { defaultValue: s })}>{itemsOfSection(area, s).map(option)}</optgroup> : itemsOfSection(area, s).map(option)))}
    </select>
  );
}

/** Settings: a grouped list on the left, the page on the right (a select above the page on narrow screens). */
function SettingsList({ area, tab, children }: { area: NavArea; tab: NavItem; children: ReactNode }) {
  const { t } = useTranslation();
  const sectionName = (id: string) => t(`nav.sections.${id}`, { defaultValue: id });
  return (
    <div>
      <p className="no-print mb-3 text-xs font-semibold uppercase tracking-wider text-muted">{t(area.titleKey)}</p>
      <div className="grid gap-5 md:grid-cols-[13.5rem_minmax(0,1fr)] md:gap-8">
        <div className="no-print md:hidden"><SettingsSelect area={area} active={tab} /></div>
        <nav aria-label={t(area.titleKey)} className="no-print hidden md:block">
          <div className="sticky top-20 space-y-5">
            {area.sections.map((s) => (
              <div key={s}>
                {s && <p className="mb-1 px-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted">{sectionName(s)}</p>}
                <ul className="space-y-0.5">
                  {itemsOfSection(area, s).map((i) => (
                    <li key={i.to}>
                      <Link to={i.to} aria-current={i.to === tab.to ? "page" : undefined}
                        className={cx("block rounded-lg px-2.5 py-1.5 text-sm font-medium transition-colors", i.to === tab.to ? "bg-brand-soft text-brand-strong" : "text-muted hover:bg-sunken hover:text-ink")}>
                        {nameOf(t, i)}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
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
    <nav aria-label={t(pages[0].tab ?? pages[0].label)} className="no-print mb-4 flex gap-1 border-b max-sm:overflow-x-auto border-line">
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
  if (placement.area.variant === "side") return <SettingsList area={placement.area} tab={placement.item}>{children}</SettingsList>;
  const pages = placement.area.families[placement.head.to];
  return pages ? <><FamilyTabs pages={pages} current={placement.item} />{children}</> : <>{children}</>;
}
