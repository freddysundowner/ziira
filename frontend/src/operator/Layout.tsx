import { Suspense, useCallback, useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";

import { cx, readStored, Spinner, useTranslation, writeStored } from "@/sdk";

import { useOperatorMe } from "./me";
import { NAV_GROUPS, visibleNav } from "./nav";
import { useAvailability } from "./pages/website/api";
import { CommandPalette } from "./shell/CommandPalette";
import { Crumbs } from "./shell/Crumbs";
import { useAlerts } from "./shell/data";
import { RiskBanners } from "./shell/RiskBanners";
import { Sidebar } from "./shell/Sidebar";
import { TopBar } from "./shell/TopBar";

const COLLAPSED = "ziira.operator.sidebar";
/** Alerts that point at one menu entry show as a number beside it. */
const BADGE_FOR: Record<string, string> = { pending_requests: "requests", payments_attention: "attempts", licences_expiring: "licences", businesses_behind: "backups", failed_jobs: "health" };

/**
 * The Super Admin's frame: a left menu that stays in view (icons only on request, a drawer on a phone), a top bar with
 * search, alerts and the account menu, risk banners, and the page with its breadcrumbs. The menu lists only what this
 * operator's role may open.
 */
export function Layout() {
  const { t } = useTranslation("operator");
  const me = useOperatorMe();
  const site = useAvailability();
  const alerts = useAlerts();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() => readStored(COLLAPSED) === "1");
  const [drawer, setDrawer] = useState(false);
  const [searching, setSearching] = useState(false);
  const permissions = me.data?.permissions ?? [];
  const missing = site.data && !site.data.available ? ["website"] : [];
  const groups = visibleNav(NAV_GROUPS, permissions, missing);

  const badges: Record<string, number> = {};
  for (const a of alerts.data?.items ?? []) {
    const id = BADGE_FOR[a.key];
    if (id) badges[id] = (badges[id] ?? 0) + a.count;
  }

  useEffect(() => setDrawer(false), [location.pathname, location.search]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const typing = /^(input|textarea|select)$/i.test((e.target as HTMLElement | null)?.tagName ?? "") || (e.target as HTMLElement | null)?.isContentEditable;
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) { e.preventDefault(); setSearching(true); }
      else if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey) { e.preventDefault(); setSearching(true); }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, []);
  const toggle = useCallback(() => setCollapsed((c) => { writeStored(COLLAPSED, c ? null : "1"); return !c; }), []);

  return (
    <div className="min-h-screen bg-bg">
      <a href="#console-main" className="sr-only z-50 rounded-lg bg-surface px-3 py-2 text-sm focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:shadow-pop">{t("shell.skip")}</a>
      <Sidebar groups={groups} collapsed={collapsed} onCollapse={toggle} drawerOpen={drawer} onCloseDrawer={() => setDrawer(false)} badges={badges} />
      <div className={cx("flex min-h-screen flex-col", collapsed ? "lg:pl-16" : "lg:pl-60")}>
        <TopBar onMenu={() => setDrawer(true)} onSearch={() => setSearching(true)} />
        <RiskBanners />
        <main id="console-main" tabIndex={-1} className="mx-auto w-full min-w-0 max-w-[1500px] flex-1 px-4 py-5 outline-none sm:px-6 sm:py-6">
          <Crumbs />
          <Suspense fallback={<div className="flex items-center justify-center gap-2 p-16 text-sm text-muted"><Spinner /> {t("loading")}</div>}><Outlet /></Suspense>
        </main>
      </div>
      <CommandPalette open={searching} onClose={() => setSearching(false)} permissions={permissions} missingFeatures={missing} />
    </div>
  );
}
