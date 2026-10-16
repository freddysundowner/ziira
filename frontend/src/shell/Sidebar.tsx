import { type KeyboardEvent, useRef, useState } from "react";
import { Link, NavLink } from "react-router-dom";

import { areaEntryPath, cx, iconFor, isSingle, type NavArea, type NavItem, type Navigation, type Placement, useNavBadges, useTranslation } from "@/sdk";

const rowClass = (active: boolean, small: boolean) =>
  cx("flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors", active ? "bg-brand-soft text-brand-strong" : "text-ink hover:bg-sunken", small && "justify-center px-0", "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand");

/** One page under a section. The "Point of sale" button is outlined, and filled only while the till itself is open. */
export function PageLink({ item, current, onGo }: { item: NavItem; current: boolean; onGo?: () => void }) {
  const { t } = useTranslation();
  const I = iconFor(item.icon);
  if (item.primary) {
    return (
      <Link to={item.to} onClick={onGo} aria-current={current ? "page" : undefined}
        className={cx("mb-1 ml-2 flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand",
          current ? "bg-brand-strong text-brand-ink shadow-card hover:bg-brand-strong/90" : "border border-line bg-surface text-ink hover:bg-sunken")}>
        <I className="h-4 w-4 shrink-0" /><span className="truncate">{t(item.label)}</span>
      </Link>
    );
  }
  return (
    <Link to={item.to} onClick={onGo} aria-current={current ? "page" : undefined}
      className={cx("relative block truncate rounded-md py-1.5 pl-9 pr-2.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand", current ? "bg-brand-soft font-semibold text-brand-strong before:absolute before:inset-y-1 before:left-0 before:w-[3px] before:rounded-full before:bg-brand" : "text-ink hover:bg-sunken")}>
      {t(item.tab ?? item.label)}
    </Link>
  );
}

/** The pages of an area: the till button, then the pages, then rarely used ones last. */
function Pages({ area, placement, onGo }: { area: NavArea; placement: Placement | null; onGo?: () => void }) {
  const here = placement?.area.id === area.id ? placement.head.to : null;
  return (
    <>
      {area.primary.map((p) => <li key={p.to}><PageLink item={p} current={here === p.to} onGo={onGo} /></li>)}
      {area.items.map((i) => <li key={i.to}><PageLink item={i} current={here === i.to} onGo={onGo} /></li>)}
      {area.setup.map((i) => <li key={i.to}><PageLink item={i} current={here === i.to} onGo={onGo} /></li>)}
    </>
  );
}

/** Collapsed to icons: the area is an icon; hovering or focusing it shows a flyout with its pages. */
function IconSection({ area, placement }: { area: NavArea; placement: Placement | null }) {
  const { t } = useTranslation();
  const [top, setTop] = useState<number | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const I = iconFor(area.icon);
  const show = () => setTop(box.current?.getBoundingClientRect().top ?? 0);
  const active = placement?.area.id === area.id;
  return (
    <div ref={box} onMouseEnter={show} onMouseLeave={() => setTop(null)} onFocus={show} onBlur={(e) => { if (!box.current?.contains(e.relatedTarget as Node)) setTop(null); }}
      onKeyDown={(e) => { if (e.key === "Escape") setTop(null); }}>
      <Link to={areaEntryPath(area)} aria-label={t(area.titleKey)} aria-haspopup={isSingle(area) ? undefined : "true"} aria-expanded={isSingle(area) ? undefined : top !== null}
        className={rowClass(active, true)}>
        <I className="h-[18px] w-[18px] shrink-0" />
      </Link>
      {top !== null && (
        <div style={{ top }} className="fixed left-[68px] z-50 min-w-48 rounded-r-xl border border-line bg-surface p-2 shadow-pop">
          <p className="px-2.5 pb-1 text-[13.5px] font-semibold text-ink">{t(area.titleKey)}</p>
          {!isSingle(area) && <ul className="space-y-0.5"><Pages area={area} placement={placement} onGo={() => setTop(null)} /></ul>}
        </div>
      )}
    </div>
  );
}

/** Up and down move between rows. */
function moveFocus(e: KeyboardEvent<HTMLElement>) {
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  const rows = [...e.currentTarget.querySelectorAll<HTMLElement>("a[href], button")];
  const at = rows.indexOf(document.activeElement as HTMLElement);
  if (at === -1) return;
  e.preventDefault();
  rows[Math.min(rows.length - 1, Math.max(0, at + (e.key === "ArrowDown" ? 1 : -1)))].focus();
}

/**
 * The sidebar: Home, then every area at once: an area with several pages is a quiet heading followed by its pages; Settings and one-page
 * areas are plain links. Collapsed to icons, each area shows its pages in a flyout.
 */
export function SidebarNav({ small, navigation, placement, homeLabel, onGo }: { small: boolean; navigation: Navigation; placement: Placement | null; homeLabel: string; onGo?: () => void }) {
  const { t } = useTranslation();
  const Home = iconFor("home");
  const badges = useNavBadges();
  return (
    <nav aria-label="Main" onKeyDown={moveFocus} className="flex-1 space-y-0.5 overflow-y-auto px-3 py-2">
      <NavLink to="/" end onClick={onGo} className={({ isActive }) => rowClass(isActive, small)} title={small ? homeLabel : undefined}>
        <Home className="h-[18px] w-[18px] shrink-0" />{!small && homeLabel}
      </NavLink>
      {navigation.entries.map((entry) => {
        if (entry.kind === "item") {
          const I = iconFor(entry.item.icon);
          return (
            <NavLink key={entry.item.to} to={entry.item.to} onClick={onGo} className={({ isActive }) => rowClass(isActive, small)} title={small ? t(entry.item.label) : undefined}>
              <I className="h-[18px] w-[18px] shrink-0" />{!small && <span className="truncate">{t(entry.item.label)}</span>}
            </NavLink>
          );
        }
        const { area } = entry;
        if (small) return <IconSection key={area.id} area={area} placement={placement} />;
        const I = iconFor(area.icon);
        const active = placement?.area.id === area.id;
        if (isSingle(area)) {
          return (
            <Link key={area.id} to={areaEntryPath(area)} onClick={onGo} aria-current={active ? "page" : undefined} className={rowClass(active, false)}>
              <I className="h-[18px] w-[18px] shrink-0" /><span className="truncate">{t(area.titleKey)}</span>
              {(badges[area.id] ?? 0) > 0 && <span className="tnum ml-auto rounded-full bg-brand px-1.5 text-xs font-semibold text-brand-ink" aria-label={String(badges[area.id])}>{badges[area.id]}</span>}
            </Link>
          );
        }
        return (
          <section key={area.id} aria-labelledby={`nav-${area.id}`} className="mt-3 border-t border-line pt-3">
            <h2 id={`nav-${area.id}`} className="flex items-center gap-3 px-2.5 pb-1.5 text-[13.5px] font-semibold text-ink"><I className="h-[18px] w-[18px] shrink-0 text-brand-strong" />{t(area.titleKey)}</h2>
            <ul className="space-y-px"><Pages area={area} placement={placement} onGo={onGo} /></ul>
          </section>
        );
      })}
    </nav>
  );
}
