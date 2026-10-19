import { Command, CircleHelp, LogOut, Menu as MenuIcon, Monitor, Moon, PanelLeftClose, PanelLeftOpen, Search, Sun, UserRound, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import {
  BrandTile, BrandWord, areaPages, buildNavigation, cx, LANGUAGES, Menu, orderedGroups, placeOf, setLanguage, Slot, useAccess, useActiveModules, useCompany, useDisplayTimeZone, useEdition, useSession,
  useTheme, useTranslation, visibleMenu, visibleRoutes,
} from "@/sdk";
import { readStored, writeStored } from "@/sdk/storage";

import { CommandPalette } from "./CommandPalette";
import { AreaFrame } from "./AreaFrame";
import { BillingNotice } from "./BillingNotice";
import { ErrorBoundary } from "./ErrorBoundary";
import { OfflineBanner } from "./OfflineBanner";
import { helpUrl } from "./help";
import { SidebarNav } from "./Sidebar";
import { SupportBanner } from "./SupportBanner";

const COLLAPSE_KEY = "ziira.sidebar";

/** The frame around every page: the sidebar (one entry per area, built from the active modules' manifests) and the area's tabs around the open page. */
export function Layout() {
  const { t, i18n } = useTranslation();
  const { signOut, me } = useSession();
  const { company } = useCompany();
  const timeZone = useDisplayTimeZone();      // pages redraw once when the company's clock becomes known
  const [theme, setTheme] = useTheme();
  const modules = useActiveModules();
  const access = useAccess();
  const items = useMemo(() => visibleMenu(modules, access), [modules, access]);
  const { edition } = useEdition();
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

  const navigation = useMemo(() => buildNavigation(modules, access, orderedGroups(edition)), [modules, access, edition]);
  const placement = useMemo(() => placeOf(navigation.areas, visibleRoutes(modules, access), location.pathname), [navigation, modules, access, location.pathname]);
  // What search shows next to a page's name: the section it is listed under.
  const areaOf = useMemo(() => {
    const out: Record<string, string> = {};
    for (const area of navigation.areas) for (const i of areaPages(area)) out[i.to] = t(area.titleKey);
    return out;
  }, [navigation, t]);

  const name = me?.full_name ?? t("account");
  const initials = name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();

  const nav = (small: boolean) => <SidebarNav small={small} navigation={navigation} placement={placement} homeLabel={t("home.menu")} onGo={() => setMobileOpen(false)} />;

  const toggleSidebar = () => { setCollapsed(!collapsed); writeStored(COLLAPSE_KEY, collapsed ? null : "1"); };
  const toggle = (
    <button type="button" onClick={toggleSidebar} aria-label={collapsed ? t("expand") : t("collapse")} title={collapsed ? t("expand") : t("collapse")}
      className="rounded-lg p-1.5 text-muted hover:bg-sunken hover:text-ink">
      {collapsed ? <PanelLeftOpen className="h-[18px] w-[18px]" /> : <PanelLeftClose className="h-[18px] w-[18px]" />}
    </button>
  );
  const brand = (small: boolean, withToggle = false) => (
    <div className={cx("flex shrink-0 items-center gap-2.5 px-4", small ? "flex-col justify-center gap-1 px-0 py-2" : "h-14", )}>
      {small ? <BrandTile size={32} /> : (
        <div className="min-w-0 flex-1 leading-tight">
          <BrandWord className="h-6" />
          <p className="mt-1 truncate text-[11px] text-muted">{company?.name ?? t("appName")}</p>
        </div>
      )}
      {withToggle && toggle}
    </div>
  );

  return (
    <div className="flex min-h-screen">
      <Slot name="shell.background" />
      <aside className={cx("no-print sticky top-0 hidden h-screen shrink-0 flex-col border-r border-line bg-surface transition-[width] md:flex", collapsed ? "w-[68px]" : "w-64")}>
        {brand(collapsed, true)}
        {nav(collapsed)}
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
        <BillingNotice />
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
              { label: t("myAccount"), icon: <UserRound className="h-4 w-4" />, onSelect: () => navigate("/admin/account") },
              ...(helpUrl() ? [{ label: t("help"), icon: <CircleHelp className="h-4 w-4" />, onSelect: () => { window.open(helpUrl(), "_blank", "noopener"); } }] : []),
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
        <main key={timeZone ?? ""} className="w-full min-w-0 flex-1 px-4 py-5 sm:px-6 sm:py-7 lg:px-8">
          <ErrorBoundary resetKey={location.pathname}><AreaFrame placement={placement}><Outlet /></AreaFrame></ErrorBoundary>
        </main>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} items={items} areaOf={areaOf} onGo={(to) => { setPalette(false); navigate(to); }} />
    </div>
  );
}
