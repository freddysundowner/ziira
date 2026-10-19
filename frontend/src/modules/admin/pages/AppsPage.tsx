import { useState } from "react";

import { api, EDITION_KEY, EmptyState, ErrorState, Input, PageHeader, Skeleton, Slot, toast, unwrap, useCompany, useEdition, useMutation, useQuery, useQueryClient, useSession, useTranslation } from "@/sdk";

import { UnitCardView } from "./apps/UnitCardView";
import { EditionPanel } from "./apps/EditionPanel";
import { UnitDialogs, type Pending } from "./apps/UnitDialogs";
import { recommendedForEdition, recommendedPlugins, type StatusFilter, titlesOf, type UnitCard, visibleCards } from "./apps/lib";

const CATALOG = ["units-catalog"];

/** Add-ons: switch modules and plugins on or off for this business, or delete a switched-off one's data. */
export default function AppsPage() {
  const { t } = useTranslation("kernel");
  const { t: shell } = useTranslation();
  const qc = useQueryClient();
  const { refresh } = useSession();
  const [pending, setPending] = useState<Pending>();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const catalog = useQuery({ queryKey: CATALOG, queryFn: () => unwrap(api.GET("/api/v1/units/catalog")) });
  const cards: UnitCard[] = catalog.data ?? [];
  const { edition } = useEdition();
  const { company } = useCompany();

  /** After any change: reload the list and the session so menus and routes follow without signing out. */
  const changed = async () => {
    await Promise.all([qc.invalidateQueries({ queryKey: CATALOG }), qc.invalidateQueries({ queryKey: EDITION_KEY }), refresh()]);
    setPending(undefined);
  };
  const path = (name: string) => ({ params: { path: { name } } });
  const enable = useMutation({
    meta: { silent: true },
    mutationFn: (u: UnitCard) => unwrap(api.POST("/api/v1/units/{name}/enable", path(u.name))),
    onSuccess: async (r) => { await changed(); toast(t("apps.enabled", { names: titlesOf(cards, r.enabled.length ? r.enabled : [r.unit.name]) }), "ok"); },
  });
  const disable = useMutation({
    meta: { silent: true },
    mutationFn: (u: UnitCard) => unwrap(api.POST("/api/v1/units/{name}/disable", path(u.name))),
    onSuccess: async (r) => { await changed(); toast(t("apps.disabled", { name: r.unit.title }), "ok"); },
  });
  const remove = useMutation({
    meta: { silent: true },
    mutationFn: (u: UnitCard) => unwrap(api.POST("/api/v1/units/{name}/remove", { ...path(u.name), body: { confirm: u.name } })),
    onSuccess: async (r) => { await changed(); toast(t("apps.removed", { name: r.unit.title }), "ok"); },
  });
  const mutations = { enable, disable, remove };

  const ask = (kind: Pending["kind"], unit: UnitCard) => { mutations[kind].reset(); setPending({ kind, unit }); };
  const recommended = new Set(recommendedPlugins(cards, edition, company?.country).map((u) => u.name));
  const shown = visibleCards(cards, query, status);
  const filters: { id: StatusFilter; label: string }[] = [{ id: "all", label: t("apps.filterAll") }, { id: "on", label: t("apps.on") }, { id: "off", label: t("apps.off") }];

  return (
    <>
      <PageHeader title={shell("nav.areas.addons")} description={t("apps.hint")} />
      <Slot name="admin.apps.notices" />
      {catalog.isLoading && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" role="status" aria-label="Loading">
          {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-40 rounded-xl" />)}
        </div>
      )}
      {catalog.error && <ErrorState title={t("apps.loadFailed")} message={catalog.error.message} onRetry={() => void catalog.refetch()} />}
      {!catalog.isLoading && !catalog.error && cards.length === 0 && <EmptyState title={t("apps.none")} hint={t("apps.noneHint")} />}
      {!catalog.isLoading && !catalog.error && <EditionPanel cards={cards} onChanged={changed} />}
      {cards.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="w-full sm:w-72"><Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("apps.search")} aria-label={t("apps.search")} /></div>
          <div role="group" aria-label={shell("nav.areas.addons")} className="inline-flex gap-0.5 rounded-lg bg-sunken p-0.5">
            {filters.map((f) => (
              <button key={f.id} type="button" aria-pressed={status === f.id} onClick={() => setStatus(f.id)}
                className={`rounded-md px-3 py-1 text-sm font-medium transition-colors ${status === f.id ? "bg-surface text-ink shadow-card" : "text-muted hover:text-ink"}`}>{f.label}</button>
            ))}
          </div>
        </div>
      )}
      {cards.length > 0 && shown.length === 0 && <EmptyState title={t("apps.noMatch")} />}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {shown.map((u) => <UnitCardView key={u.name} unit={u} all={cards} recommended={recommended.has(u.name)} forEdition={recommendedForEdition(u, edition?.id)} onEnable={() => ask("enable", u)} onDisable={() => ask("disable", u)} onRemove={() => ask("remove", u)} />)}
      </div>
      <UnitDialogs pending={pending} all={cards} mutations={mutations} onClose={() => setPending(undefined)} />
    </>
  );
}
