import { Command, LogOut, Menu as MenuIcon, Monitor, Moon, PanelLeftClose, PanelLeftOpen, Search, Sun, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import {
  cx, iconFor, LANGUAGES, MENU_GROUPS, Menu, setLanguage, useAccess, useActiveModules, useCompany, useSession, useTheme, useTranslation, visibleMenu,
  type MenuItem,
} from "@/sdk";
import { readStored, writeStored } from "@/sdk/storage";

import { CommandPalette } from "./CommandPalette";
import { ErrorBoundary } from "./ErrorBoundary";
import { OfflineBanner } from "./OfflineBanner";
import { SupportBanner } from "./SupportBanner";

const COLLAPSE_KEY = "ziira.sidebar";

/** The frame around every page: the menu comes from the active modules' manifests, grouped into sections. */
export function Layout() {
  const { t, i18n } = useTranslation();
  const { signOut, me } = useSession();
  const { company } = useCompany();
  const [theme, setTheme] = useTheme();
  const items = visibleMenu(useActiveModules(), useAccess());
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(readStored(COLLAPSE_KEY) === "1");
  const [palette, setPalette] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => setMobileOpen(false), [location.pathname]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, []);

  const groups = useMemo(() => {
    const out: { id: string; items: MenuItem[] }[] = [];
    const top = items.filter((i) => !i.group);
    if (top.length) out.push({ id: "", items: top });
    for (const g of MENU_GROUPS) {
      const inGroup = items.filter((i) => i.group === g);
      if (inGroup.length) out.push({ id: g, items: inGroup });
    }
    return out;
  }, [items]);

  const name = me?.full_name ?? t("account");
  const initials = name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();

  const link = (small: boolean) => ({ isActive }: { isActive: boolean }) =>
    cx("group flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors", isActive ? "bg-brand-soft text-brand-strong" : "text-muted hover:bg-sunken hover:text-ink", small && "justify-center px-0");

  const nav = (small: boolean) => (
    <nav aria-label="Main" className="flex-1 space-y-5 overflow-y-auto px-3 py-2">
      <NavLink to="/" end className={link(small)} title={t("home.menu")}>
        {(() => { const I = iconFor("home"); return <I className="h-[18px] w-[18px] shrink-0" />; })()}
        {!small && t("home.menu")}
      </NavLink>
      {groups.map((g) => (
        <div key={g.id || "top"}>
          {g.id && !small && <p className="mb-1 px-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted">{t(`nav.${g.id}`)}</p>}
          {g.id && small && <hr className="mx-2 mb-2 border-line" />}
          <div className="space-y-0.5">
            {g.items.map((item) => {
              const I = iconFor(item.icon);
              return (
                <NavLink key={item.to} to={item.to} className={link(small)} title={small ? t(item.label) : undefined}>
                  <I className="h-[18px] w-[18px] shrink-0" />
                  {!small && <span className="truncate">{t(item.label)}</span>}
                </NavLink>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );

  const brand = (small: boolean) => (
    <div className={cx("flex h-14 shrink-0 items-center gap-2.5 px-4", small && "justify-center px-0")}>
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand text-sm font-bold text-brand-ink">Z</div>
      {!small && (
        <div className="min-w-0 leading-tight">
          <p className="truncate text-sm font-semibold">{company?.name ?? t("appName")}</p>
          <p className="text-[11px] text-muted">{t("appName")}</p>
        </div>
      )}
    </div>
  );

  return (
    <div className="flex min-h-screen">
      <aside className={cx("no-print sticky top-0 hidden h-screen shrink-0 flex-col border-r border-line bg-surface transition-[width] md:flex", collapsed ? "w-[68px]" : "w-64")}>
        {brand(collapsed)}
        {nav(collapsed)}
        <button onClick={() => { setCollapsed(!collapsed); writeStored(COLLAPSE_KEY, collapsed ? null : "1"); }}
          className="m-3 flex items-center justify-center gap-2 rounded-lg py-2 text-xs text-muted hover:bg-sunken hover:text-ink" aria-label={collapsed ? t("expand") : t("collapse")}>
          {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <><PanelLeftClose className="h-4 w-4" />{t("collapse")}</>}
        </button>
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden" onMouseDown={(e) => e.target === e.currentTarget && setMobileOpen(false)}>
          <div className="absolute inset-0 bg-black/50 animate-fade" onClick={() => setMobileOpen(false)} />
          <aside className="relative flex h-full w-72 max-w-[85vw] flex-col bg-surface shadow-pop animate-slideleft">
            <div className="flex items-center justify-between pr-2">{brand(false)}<button aria-label={t("close")} onClick={() => setMobileOpen(false)} className="rounded-lg p-2 text-muted hover:bg-sunken"><X className="h-5 w-5" /></button></div>
            {nav(false)}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <OfflineBanner />
        <SupportBanner />
        <header className="app-bar sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-line bg-surface/85 px-3 backdrop-blur sm:px-5">
          <button aria-label={t("menu")} onClick={() => setMobileOpen(true)} className="rounded-lg p-2 text-muted hover:bg-sunken md:hidden"><MenuIcon className="h-5 w-5" /></button>
          <button onClick={() => setPalette(true)} className="flex h-9 w-full max-w-md items-center gap-2 rounded-lg border border-line bg-bg px-3 text-sm text-muted hover:border-muted/50">
            <Search className="h-4 w-4" /> <span className="flex-1 text-left">{t("search")}</span>
            <kbd className="hidden items-center gap-0.5 rounded border border-line bg-surface px-1.5 text-[11px] sm:flex"><Command className="h-3 w-3" />K</kbd>
          </button>
          <div className="flex-1" />
          <Menu label={t("account")} up={false}
            trigger={<span className="flex items-center gap-2 rounded-lg p-1 pr-2 hover:bg-sunken"><span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand-strong">{initials || "?"}</span><span className="hidden max-w-[10rem] truncate text-sm font-medium sm:block">{name}</span></span>}
            items={[
              { label: me?.email ?? name, onSelect: () => undefined, disabled: true },
              "separator",
              { label: t("theme.light"), icon: <Sun className="h-4 w-4" />, onSelect: () => setTheme("light"), disabled: theme === "light" },
              { label: t("theme.dark"), icon: <Moon className="h-4 w-4" />, onSelect: () => setTheme("dark"), disabled: theme === "dark" },
              { label: t("theme.system"), icon: <Monitor className="h-4 w-4" />, onSelect: () => setTheme("system"), disabled: theme === "system" },
              "separator",
              ...Object.entries(LANGUAGES).map(([code, label]) => ({ label, onSelect: () => setLanguage(code as keyof typeof LANGUAGES), disabled: i18n.language === code })),
              "separator",
              { label: t("signOut"), icon: <LogOut className="h-4 w-4" />, onSelect: () => void signOut(), danger: true },
            ]} />
        </header>
        <main className="w-full min-w-0 flex-1 px-4 py-5 sm:px-6 sm:py-7 lg:px-8">
          <ErrorBoundary resetKey={location.pathname}><Outlet /></ErrorBoundary>
        </main>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} items={items} onGo={(to) => { setPalette(false); navigate(to); }} />
    </div>
  );
}
