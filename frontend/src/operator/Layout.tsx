import { LogOut, Menu as MenuIcon, ShieldAlert, ShieldCheck, UserCog, X } from "lucide-react";
import { Suspense, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { Alert, Badge, Button, cx, LANGUAGES, setLanguage, Spinner, useTranslation } from "@/sdk";

import { useAvailability } from "./pages/website/api";
import { useOperatorMe } from "./me";
import { NAV_GROUPS, visibleNav } from "./nav";
import { useOperator } from "./session";

const DISMISSED = "ziira.operator.mfa-warning";

function warningDismissed(): boolean {
  try {
    return sessionStorage.getItem(DISMISSED) === "1";
  } catch {
    return false;
  }
}

/**
 * Shown in production when staff sign in with a password alone: one stolen password would give control of every
 * business. It can be closed for this browser session; it comes back the next time.
 */
function NoSecondFactorWarning() {
  const { t } = useTranslation("operator");
  const [hidden, setHidden] = useState(warningDismissed);
  if (hidden) return null;
  const dismiss = () => {
    try {
      sessionStorage.setItem(DISMISSED, "1");
    } catch {
      // closed for now; it returns on the next load
    }
    setHidden(true);
  };
  return (
    <div className="mx-auto max-w-7xl px-4 pt-3">
      <Alert tone="warn">
        <div className="flex items-start gap-3">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="font-medium">{t("security.noSecondFactorTitle")}</p>
            <p className="text-sm">{t("security.noSecondFactor")}</p>
          </div>
          <Button variant="ghost" size="sm" onClick={dismiss}>{t("security.dismiss")}</Button>
        </div>
      </Alert>
    </div>
  );
}

/**
 * The console's frame: a bar on top and the grouped menu beside the page (behind a Menu button on a phone). The menu
 * lists only what this operator's role may open.
 */
export function Layout() {
  const { t, i18n } = useTranslation("operator");
  const { signOut } = useOperator();
  const me = useOperatorMe();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const site = useAvailability();
  const groups = visibleNav(NAV_GROUPS, me.data?.permissions ?? [], site.data && !site.data.available ? ["website"] : []);

  useEffect(() => setOpen(false), [location.pathname]);

  return (
    <div className="min-h-screen bg-bg">
      <header className="sticky top-0 z-30 border-b border-line bg-surface">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2.5">
          <Button variant="secondary" size="sm" className="lg:hidden" aria-expanded={open} aria-controls="console-nav" onClick={() => setOpen((o) => !o)}>
            {open ? <X className="h-4 w-4" /> : <MenuIcon className="h-4 w-4" />} {t("nav.menu")}
          </Button>
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand text-sm font-bold text-brand-ink"><ShieldCheck className="h-4 w-4" /></div>
            <span className="hidden text-sm font-semibold sm:inline">{t("appName")}</span>
          </div>
          <div className="flex-1" />
          <select aria-label={t("language")} value={i18n.language} onChange={(e) => setLanguage(e.target.value as keyof typeof LANGUAGES)}
            className="hidden rounded-lg border border-line bg-surface px-2 py-1 text-xs sm:block">
            {Object.entries(LANGUAGES).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
          <span className="hidden items-center gap-2 text-xs text-muted md:flex">
            {me.data?.name}
            {me.data?.role && <Badge tone="brand">{t(`operators.roles.${me.data.role}`, me.data.role)}</Badge>}
          </span>
          <NavLink to="/operator/account" className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm text-muted hover:bg-sunken hover:text-ink">
            <UserCog className="h-4 w-4" /> <span className="hidden sm:inline">{t("account.link")}</span>
          </NavLink>
          <Button variant="secondary" size="sm" onClick={() => void signOut()}><LogOut className="h-4 w-4" /> {t("signOut")}</Button>
        </div>
      </header>
      {me.data?.mfa_off_in_production && <NoSecondFactorWarning />}
      <div className="mx-auto flex max-w-7xl flex-col gap-0 px-4 lg:flex-row lg:gap-8">
        <nav id="console-nav" aria-label={t("nav.label")}
          className={cx("shrink-0 py-4 lg:sticky lg:top-14 lg:block lg:max-h-[calc(100vh-3.5rem)] lg:w-52 lg:self-start lg:overflow-y-auto lg:py-6", open ? "block border-b border-line" : "hidden")}>
          {groups.map((g) => (
            <div key={g.key} className="mb-3">
              <p className="px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-muted">{t(g.key)}</p>
              <ul className="space-y-0.5">
                {g.items.map(({ to, key, icon: Icon }) => (
                  <li key={to}>
                    <NavLink to={to} className={({ isActive }) => cx("flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium", isActive ? "bg-sunken text-ink" : "text-muted hover:bg-sunken/60 hover:text-ink")}>
                      <Icon className="h-4 w-4" /> {t(key)}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <main className="min-w-0 flex-1 py-6">
          <Suspense fallback={<div className="flex items-center justify-center gap-2 p-16 text-sm text-muted"><Spinner /> {t("loading")}</div>}><Outlet /></Suspense>
        </main>
      </div>
    </div>
  );
}
