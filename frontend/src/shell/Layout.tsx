import { NavLink, Outlet } from "react-router-dom";

import { LANGUAGES, setLanguage, useAccess, useActiveModules, useSession, useTranslation, visibleMenu } from "@/sdk";

/** The frame around every page: the menu comes from the active modules' manifests. */
export function Layout() {
  const { t, i18n } = useTranslation();
  const { signOut } = useSession();
  const menu = visibleMenu(useActiveModules(), useAccess());
  const link = ({ isActive }: { isActive: boolean }) =>
    `block rounded-md px-3 py-2 text-sm ${isActive ? "bg-brand-light font-medium text-brand-dark" : "hover:bg-slate-100"}`;

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-56 flex-col border-r border-slate-200 bg-white p-3">
        <div className="mb-4 px-3 text-lg font-bold text-brand">{t("appName")}</div>
        <nav className="flex-1 space-y-1">
          <NavLink to="/" end className={link}>{t("home.menu")}</NavLink>
          {menu.map((item) => <NavLink key={item.to} to={item.to} className={link}>{t(item.label)}</NavLink>)}
        </nav>
        <select
          aria-label={t("language")}
          className="mb-2 rounded-md border border-slate-300 px-2 py-1 text-sm"
          value={i18n.language}
          onChange={(e) => setLanguage(e.target.value as keyof typeof LANGUAGES)}
        >
          {Object.entries(LANGUAGES).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
        </select>
        <button className="rounded-md px-3 py-2 text-left text-sm hover:bg-slate-100" onClick={() => void signOut()}>
          {t("signOut")}
        </button>
      </aside>
      <main className="flex-1 p-6"><Outlet /></main>
    </div>
  );
}
