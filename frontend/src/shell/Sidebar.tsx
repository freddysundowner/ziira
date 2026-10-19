import { ChevronDown } from "lucide-react";
import { type KeyboardEvent, useRef, useState } from "react";
import { Link, NavLink } from "react-router-dom";

import { areaEntryPath, cx, iconFor, isSingle, type NavArea, type NavItem, type Navigation, type Placement, useNavBadges, useTranslation } from "@/sdk";
import { readStored, writeStored } from "@/sdk/storage";

const OPEN_KEY = "ziira.sidebar.sections";
/** Sections the person opened or closed by hand (id -> open); everything else follows the default: Intelligence open, the rest closed. */
function readChoices(): Record<string, boolean> {
  try { return JSON.parse(readStored(OPEN_KEY) ?? "{}") as Record<string, boolean>; } catch { return {}; }
}
const OPEN_BY_DEFAULT = new Set(["command"]);

const rowClass = (active: boolean, small: boolean) =>
  cx("flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-[13px] transition-colors", active ? "bg-brand-soft font-bold text-brand-strong" : "font-medium text-ink/80 hover:bg-sunken hover:text-ink", small && "justify-center px-0", "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand");

/** One page under a section. The "Point of sale" button is outlined, and filled only while the till itself is open. */
export function PageLink({ item, current, onGo }: { item: NavItem; current: boolean; onGo?: () => void }) {
  const { t } = useTranslation();
  const I = iconFor(item.icon);
  if (item.primary) {
    return (
      <Link to={item.to} onClick={onGo} aria-current={current ? "page" : undefined}
        className={cx("mb-1 ml-1 mr-1 flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand",
          current ? "btn-gradient font-semibold" : "border border-line font-semibold text-ink hover:bg-sunken")}>
        <I className="h-4 w-4 shrink-0" /><span className="truncate">{t(item.label)}</span>
      </Link>
    );
  }
  return (
    <Link to={item.to} onClick={onGo} aria-current={current ? "page" : undefined}
      className={cx("relative block truncate rounded-lg py-2 pl-10 pr-3 text-[13px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand", current ? "bg-brand-soft font-bold text-brand-strong before:absolute before:inset-y-2 before:left-1 before:w-[3px] before:rounded-full before:bg-brand-gradient" : "font-medium text-ink/80 hover:bg-sunken hover:text-ink")}>
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
        <div style={{ top }} className="fixed left-[68px] z-50 min-w-48 rounded-r-xl border border-line bg-surface p-2.5 shadow-pop">
          <p className="eyebrow px-2.5 pb-1.5 pt-1">{t(area.titleKey)}</p>
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
  const [choices, setChoices] = useState(readChoices);
  const pinned = (e: Navigation["entries"][number]) => e.kind === "area" && (e.area.id === "addons" || e.area.id === "settings");
  const main = navigation.entries.filter((e) => !pinned(e));
  const footer = navigation.entries.filter(pinned).sort((x, y) => Number(y.kind === "area" && y.area.id === "addons") - Number(x.kind === "area" && x.area.id === "addons"));
  const row = (entry: Navigation["entries"][number]) => {
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
          {(badges[area.id] ?? 0) > 0 && <span className="tnum ml-auto rounded-full bg-sunken px-2 py-0.5 text-[11px] font-semibold text-muted" aria-label={String(badges[area.id])}>{badges[area.id]}</span>}
        </Link>
      );
    }
    // The section you are in is always open; otherwise the person's own choice, then the default.
    const open = active || (choices[area.id] ?? OPEN_BY_DEFAULT.has(area.id));
    const flip = () => {
      const next = { ...choices, [area.id]: !open };
      setChoices(next);
      writeStored(OPEN_KEY, JSON.stringify(next));
    };
    return (
      <section key={area.id} aria-labelledby={`nav-${area.id}`} className="mt-3 border-t border-line pt-1.5">
        <h2 id={`nav-${area.id}`} className="eyebrow">
          <button type="button" onClick={flip} aria-expanded={open} aria-controls={`nav-list-${area.id}`} disabled={active}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left uppercase hover:bg-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-default disabled:hover:bg-transparent">
            <I className="h-4 w-4 shrink-0 text-brand-strong" /><span className="flex-1 truncate">{t(area.titleKey)}</span>
            {!active && <ChevronDown className={cx("h-4 w-4 shrink-0 text-muted transition-transform", !open && "-rotate-90")} aria-hidden />}
          </button>
        </h2>
        {open && <ul id={`nav-list-${area.id}`} className="mt-0.5 space-y-px"><Pages area={area} placement={placement} onGo={onGo} /></ul>}
      </section>
    );
  };
  return (
    <>
      <nav aria-label="Main" onKeyDown={moveFocus} className="flex-1 space-y-0.5 overflow-y-auto px-2.5 py-3 [scrollbar-width:thin]">
        <NavLink to="/" end onClick={onGo} className={({ isActive }) => rowClass(isActive, small)} title={small ? homeLabel : undefined}>
          <Home className="h-[18px] w-[18px] shrink-0" />{!small && homeLabel}
        </NavLink>
        {main.map(row)}
      </nav>
      {footer.length > 0 && (
        <nav aria-label="Add-ons and settings" onKeyDown={moveFocus} className="shrink-0 space-y-0.5 border-t border-line px-2.5 py-2.5">
          {footer.map(row)}
        </nav>
      )}
    </>
  );
}
