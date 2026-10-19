import { useEffect, useMemo, useState } from "react";
import { Link, Navigate } from "react-router-dom";

import { cx, hasLanded, iconFor, areaEntryPath, buildNavigation, landingTarget, orderedGroups, setLanded, Skeleton, Slot, useAccess, useActiveModules, useEdition, useSession, useTranslation, visibleRoutes } from "@/sdk";

import { Checklist } from "./Checklist";
import { WidgetCard } from "./WidgetCard";

/** The home page: a greeting, shortcuts to the screens you may open, and boxes that modules add through the "dashboard.widgets" slot. */
export function Home() {
  const { t } = useTranslation();
  const { me } = useSession();
  const modules = useActiveModules();
  const access = useAccess();
  const { mine, edition, isLoading } = useEdition();
  // Shortcuts: the till first, then each working area (not Settings), each opening on its first page.
  const shortcuts = useMemo(() => {
    const { areas } = buildNavigation(modules, access, orderedGroups(edition));
    const till = areas.flatMap((a) => a.primary).map((p) => ({ to: p.to, label: t(p.label), icon: p.icon }));
    const rest = areas.filter((a) => a.id !== "settings").map((a) => ({ to: areaEntryPath(a), label: t(a.titleKey), icon: a.icon }));
    return [...till, ...rest].slice(0, 8);
  }, [modules, access, edition, t]);
  const openable = useMemo(() => new Set(visibleRoutes(modules, access).map((r) => r.path)), [modules, access]);
  const [landed] = useState(hasLanded);          // read once: the page opened first after sign-in is the edition's, then Home is Home
  useEffect(() => { if (!isLoading) setLanded(); }, [isLoading]);
  const target = landingTarget(edition?.landing, openable, landed);
  if (isLoading && !landed) return <Skeleton className="h-40 rounded-xl" />;
  if (target) return <Navigate to={target} replace />;
  const hour = new Date().getHours();
  const greeting = hour < 12 ? t("home.morning") : hour < 18 ? t("home.afternoon") : t("home.evening");
  const first = me?.full_name?.split(/\s+/)[0];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{greeting}{first ? `, ${first}` : ""}</h1>
        <p className="mt-1 text-sm text-muted">{t("home.subtitle")}</p>
      </div>
      {mine && <Checklist edition={mine.edition} done={mine.done} dismissed={mine.dismissed} openable={openable} />}
      {shortcuts.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {shortcuts.map((i) => {
            const I = iconFor(i.icon);
            return (
              <Link key={i.to} to={i.to} className="group flex items-center gap-3 rounded-xl border border-line bg-surface p-3.5 shadow-card transition-colors hover:border-brand/50">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-soft text-brand-strong"><I className="h-[18px] w-[18px]" /></span>
                <span className="text-sm font-medium">{i.label}</span>
              </Link>
            );
          })}
        </div>
      )}
      {/* grid-cols-1 (not an automatic column) lets a wide widget shrink instead of widening the page on a phone */}
      <div className={cx("grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3")}>
        <Slot
          name="dashboard.widgets"
          render={(c, content) => <WidgetCard title={c.label ? t(c.label) : undefined}>{content}</WidgetCard>}
        />
      </div>
    </div>
  );
}
