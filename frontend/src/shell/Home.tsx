import { ChevronDown } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, Navigate } from "react-router-dom";

import { areaEntryPath, buildNavigation, cx, hasLanded, iconFor, landingTarget, orderedGroups, setLanded, SIDEBAR, Skeleton, SlotContent, useAccess, useActiveModules, useEdition, useSession, useSlot, useTranslation, visibleRoutes, type ActiveContribution } from "@/sdk";

import { Checklist } from "./Checklist";
import { arrange, orderAreas, PROFILES, profileFor, WIDE } from "./homeProfiles";
import { WidgetCard } from "./WidgetCard";

/** A Home box is named by its slot label (the same key in homeProfiles.ts). */
const idOf = (c: ActiveContribution) => c.label ?? `${c.unit}:widget`;

/**
 * The home page: a greeting, shortcuts to the screens you may open, and the boxes that modules add through the "dashboard.widgets" slot,
 * arranged for the kind of business (homeProfiles.ts): number tiles first, then lists, the rest behind "More".
 * Notices about the account (a trial ending ...) are not boxes: BillingNotice shows them as a slim strip above the page.
 */
export function Home() {
  const { t } = useTranslation();
  const { me } = useSession();
  const modules = useActiveModules();
  const access = useAccess();
  const { enabledUnits } = useSession();
  const { mine, edition, isLoading } = useEdition();
  const kind = profileFor(edition?.id, enabledUnits);
  const profile = PROFILES[kind];
  const widgets = useSlot("dashboard.widgets");
  const placed = useMemo(() => arrange(profile, widgets.map(idOf)), [profile, widgets]);
  const byId = useMemo(() => new Map(widgets.map((c) => [idOf(c), c])), [widgets]);
  const [showMore, setShowMore] = useState(false);
  // Shortcuts: the till first, then each working area (not Settings), each opening on its first page.
  const shortcuts = useMemo(() => {
    const { areas } = buildNavigation(modules, access, orderedGroups(edition), SIDEBAR[kind]);
    const till = areas.flatMap((a) => a.primary).map((p) => ({ to: p.to, label: t(p.label), icon: p.icon }));
    const rest = orderAreas(areas.filter((a) => a.id !== "settings"), profile.areas).map((a) => ({ to: areaEntryPath(a), label: t(a.titleKey), icon: a.icon }));
    return [...till, ...rest].slice(0, 7);
  }, [modules, access, edition, t, profile, kind]);
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
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">{greeting}{first ? `, ${first}` : ""}</h1>
        <p className="mt-1 text-sm text-muted">{t("home.subtitle")}</p>
      </div>
      {mine && <Checklist edition={mine.edition} done={mine.done} dismissed={mine.dismissed} openable={openable} />}
      {shortcuts.length > 0 && (
        <nav aria-label={t("home.shortcuts")} className="flex flex-wrap gap-2">
          {shortcuts.map((i) => {
            const I = iconFor(i.icon);
            return (
              <Link key={i.to} to={i.to} className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium shadow-card transition-colors hover:border-brand/50">
                <I className="h-4 w-4 text-brand-strong" aria-hidden />{i.label}
              </Link>
            );
          })}
        </nav>
      )}
      {placed.stats.length > 0 && (
        <section aria-label={t("home.numbers")} className="grid grid-cols-1 items-start gap-3 min-[420px]:grid-cols-2 lg:grid-cols-4">
          {placed.stats.map((id) => <Box key={id} c={byId.get(id)} variant="stat" />)}
        </section>
      )}
      {placed.lists.length > 0 && (
        <section aria-label={t("home.lists")} className="grid grid-cols-1 items-start gap-3 md:grid-cols-2">
          {placed.lists.map((id) => <Box key={id} c={byId.get(id)} variant="full" />)}
        </section>
      )}
      {placed.more.length > 0 && (
        <section>
          <button type="button" aria-expanded={showMore} onClick={() => setShowMore((v) => !v)} className="flex items-center gap-1.5 text-sm font-medium text-muted hover:text-ink">
            <ChevronDown className={cx("h-4 w-4 transition-transform", showMore && "rotate-180")} aria-hidden />{t("home.more")}
          </button>
          {showMore && (
            <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {placed.more.map((id) => <Box key={id} c={byId.get(id)} variant="full" />)}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

/** One Home box: the module's widget in its card (`stat`: a compact number tile). */
function Box({ c, variant }: { c: ActiveContribution | undefined; variant: "stat" | "full" }) {
  const { t } = useTranslation();
  if (!c) return null;
  return (
    <WidgetCard title={c.label ? t(c.label) : undefined} tile={variant === "stat"} wide={variant === "stat" && WIDE.has(idOf(c))}>
      <SlotContent contribution={c} props={{ variant }} />
    </WidgetCard>
  );
}
