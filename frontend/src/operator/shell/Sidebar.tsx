import { ChevronsLeft, ChevronsRight, X } from "lucide-react";
import { Fragment, useEffect } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { BrandMark, cx, IconButton, useTranslation } from "@/sdk";

import { isActive, type NavGroup } from "../nav";

interface Props {
  groups: NavGroup[];
  /** Icons only (a desktop choice, remembered). */
  collapsed: boolean;
  onCollapse: () => void;
  /** Phone: the menu is a drawer, open or closed. */
  drawerOpen: boolean;
  onCloseDrawer: () => void;
  /** Items that have something waiting: the number shows beside them. */
  badges?: Record<string, number>;
}

/**
 * The persistent left menu: grouped sections with headings, always visible from the large breakpoint (narrowed to icons
 * on request) and a drawer on a phone. Only what this operator's role may open is listed.
 */
export function Sidebar({ groups, collapsed, onCollapse, drawerOpen, onCloseDrawer, badges = {} }: Props) {
  const { t } = useTranslation("operator");
  const { pathname, search } = useLocation();

  useEffect(() => {
    if (!drawerOpen) return;
    const key = (e: KeyboardEvent) => e.key === "Escape" && onCloseDrawer();
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [drawerOpen, onCloseDrawer]);

  const list = (narrow: boolean) => (
    <nav id={narrow ? "console-nav" : "console-nav-drawer"} aria-label={t("nav.label")} className="flex-1 overflow-y-auto px-2.5 pb-4">
      {groups.map((g, index) => (
        <Fragment key={g.key}>
          {narrow ? (index > 0 && <hr className="mx-2 my-2 border-line" />) : <p className="eyebrow px-3 pb-1.5 pt-4">{t(g.key)}</p>}
          <ul className="space-y-0.5" aria-label={narrow ? t(g.key) : undefined}>
            {g.items.map((item) => {
              const active = isActive(item, pathname, search);
              const count = badges[item.id];
              const label = t(`nav.i.${item.id}`);
              return (
                <li key={item.id}>
                  <NavLink to={item.to} title={narrow ? label : undefined} aria-label={narrow ? label : undefined} aria-current={active ? "page" : undefined}
                    className={cx("relative flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-[13px] font-medium outline-none focus-visible:ring-2 focus-visible:ring-brand",
                      narrow && "justify-center px-0", active ? "bg-brand-soft font-bold text-brand-strong" : "text-ink/80 hover:bg-sunken hover:text-ink")}>
                    <item.icon className="h-4 w-4 shrink-0" aria-hidden />
                    {!narrow && <span className="min-w-0 flex-1 truncate">{label}</span>}
                    {count ? (
                      <span className={cx("tnum rounded-full bg-bad px-1.5 text-[11px] font-semibold leading-4 text-bad-ink", narrow && "absolute right-1 top-0.5")} aria-label={t("shell.waiting", { count })}>{count}</span>
                    ) : null}
                  </NavLink>
                </li>
              );
            })}
          </ul>
        </Fragment>
      ))}
    </nav>
  );

  const brand = (narrow: boolean) => (
    <div className={cx("flex h-16 shrink-0 items-center gap-2.5 border-b border-line px-5 lg:h-[76px]", narrow && "justify-center px-0")}>
      <BrandMark className="h-6 w-auto shrink-0" />
      {!narrow && <span className="truncate text-[21px] font-bold leading-none tracking-[-0.04em]">{t("appName")}</span>}
    </div>
  );

  return (
    <>
      <aside className={cx("fixed inset-y-0 left-0 z-30 hidden flex-col border-r border-line bg-surface lg:flex", collapsed ? "w-16" : "w-60")}>
        {brand(collapsed)}
        {list(collapsed)}
        <div className="border-t border-line p-2">
          <button type="button" onClick={onCollapse} aria-label={collapsed ? t("shell.expand") : t("shell.collapse")} title={collapsed ? t("shell.expand") : t("shell.collapse")}
            className="flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs text-muted hover:bg-sunken hover:text-ink focus-visible:ring-2 focus-visible:ring-brand">
            {collapsed ? <ChevronsRight className="h-4 w-4" /> : <><ChevronsLeft className="h-4 w-4" /> {t("shell.collapse")}</>}
          </button>
        </div>
      </aside>
      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-navy/60 animate-fade" onClick={onCloseDrawer} aria-hidden />
          <aside className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-surface shadow-pop animate-slideleft motion-reduce:animate-none" role="dialog" aria-modal="true" aria-label={t("nav.label")}>
            <div className="flex items-center justify-between pr-2">
              {brand(false)}
              <IconButton label={t("shell.closeMenu")} onClick={onCloseDrawer}><X className="h-4 w-4" /></IconButton>
            </div>
            {list(false)}
          </aside>
        </div>
      )}
    </>
  );
}
