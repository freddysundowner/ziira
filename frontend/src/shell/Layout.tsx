import { Command, CircleHelp, LogOut, Menu as MenuIcon, Monitor, Moon, PanelLeftClose, PanelLeftOpen, Search, Sun, UserRound, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import {
  BrandMark, areaPages, buildNavigation, cx, LANGUAGES, Menu, orderedGroups, placeOf, setLanguage, Slot, useAccess, useActiveModules, useCompany, useDisplayTimeZone, useEdition, useSession,
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
      className="rounded-lg p-2 text-muted hover:bg-sunken hover:text-ink">
      {collapsed ? <PanelLeftOpen className="h-[18px] w-[18px]" /> : <PanelLeftClose className="h-[18px] w-[18px]" />}
    </button>
  );
  const brand = (small: boolean, withToggle = false) => (
    <>
      <div className={cx("flex shrink-0 items-center gap-2.5 border-b border-line", small ? "flex-col justify-center gap-1 px-0 py-3" : "h-16 px-5 md:h-[76px]")}>
        <BrandMark className={small ? "h-5 w-auto" : "h-6 w-auto"} />
        {!small && <span className="min-w-0 flex-1 truncate text-[21px] font-bold leading-none tracking-[-0.04em] text-ink">{t("appName")}</span>}
        {withToggle && toggle}
      </div>
      {/* The business block under the brand: who you are working in. */}
      {!small && (
        <div className="shrink-0 border-b border-line px-3.5 pb-3.5 pt-4">
          <div className="flex w-full items-center gap-2.5 rounded-[10px] border border-line bg-surface p-2.5 text-left">
            <span className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-[9px] bg-brand-soft text-sm font-bold text-brand-strong" aria-hidden>{(company?.name ?? t("appName")).slice(0, 1).toUpperCase()}</span>
            <span className="min-w-0 flex-1">
              <strong className="block truncate text-[13px] font-semibold leading-tight">{company?.name ?? t("appName")}</strong>
              {company?.currency && <small className="mt-0.5 block text-[11px] text-muted">{company.currency}</small>}
            </span>
          </div>
        </div>
      )}
    </>
  );

  return (
    <div className="flex min-h-screen">
      <Slot name="shell.background" />
      <aside className={cx("no-print sticky top-0 hidden h-screen shrink-0 flex-col border-r border-line bg-surface transition-[width] md:flex", collapsed ? "w-[68px]" : "w-[250px]")}>
        {brand(collapsed, true)}
        {nav(collapsed)}
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden" onMouseDown={(e) => e.target === e.currentTarget && setMobileOpen(false)}>
          <div className="absolute inset-0 bg-navy/60 animate-fade" onClick={() => setMobileOpen(false)} />
          <aside className="relative flex h-full w-72 max-w-[85vw] flex-col bg-surface shadow-pop animate-slideleft">
            <div className="absolute right-2 top-3 z-10"><button aria-label={t("close")} onClick={() => setMobileOpen(false)} className="rounded-lg p-2 text-muted hover:bg-sunken"><X className="h-5 w-5" /></button></div>
            {brand(false)}
            {nav(false)}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <OfflineBanner />
        <SupportBanner />
        <BillingNotice />
        <header className="app-bar sticky top-0 z-30 flex h-16 items-center gap-2 border-b border-line bg-surface/90 px-3 backdrop-blur sm:gap-4 md:h-[76px] md:px-7">
          <button aria-label={t("menu")} onClick={() => setMobileOpen(true)} className="rounded-lg p-2 text-muted hover:bg-sunken md:hidden"><MenuIcon className="h-5 w-5" /></button>
          <button onClick={() => setPalette(true)} className="flex h-10 w-full max-w-[460px] items-center gap-2.5 rounded-[10px] border border-line bg-bg px-3.5 text-sm text-muted hover:border-muted/50">
            <Search className="h-4 w-4" /> <span className="flex-1 text-left">{t("search")}</span>
            <kbd className="hidden items-center gap-0.5 rounded border border-line bg-surface px-1.5 text-[11px] sm:flex"><Command className="h-3 w-3" />K</kbd>
          </button>
          <div className="flex-1" />
          <Menu label={t("account")} up={false}
            trigger={<span className="flex items-center gap-2.5 rounded-lg p-1 pr-2 hover:bg-sunken"><span className="flex h-[34px] w-[34px] items-center justify-center rounded-full bg-brand-soft text-xs font-bold text-brand-strong">{initials || "?"}</span><span className="hidden max-w-[11rem] text-left sm:block"><strong className="block truncate text-xs font-semibold leading-tight">{name}</strong>{company?.name && <small className="mt-0.5 block truncate text-[11px] text-muted">{company.name}</small>}</span></span>}
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
        <main key={timeZone ?? ""} className="w-full min-w-0 flex-1 px-4 py-6 sm:px-6 sm:py-7 lg:px-[30px] lg:pb-10">
          <ErrorBoundary resetKey={location.pathname}><AreaFrame placement={placement}><Outlet /></AreaFrame></ErrorBoundary>
        </main>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} items={items} areaOf={areaOf} onGo={(to) => { setPalette(false); navigate(to); }} />
    </div>
  );
}
