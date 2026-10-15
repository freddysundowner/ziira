import { Blocks, Plug } from "lucide-react";
import { useState } from "react";

import { api, EmptyState, ErrorState, PageHeader, Skeleton, toast, unwrap, useMutation, useQuery, useQueryClient, useSession, useTranslation } from "@/sdk";

import { UnitCardView } from "./apps/UnitCardView";
import { UnitDialogs, type Pending } from "./apps/UnitDialogs";
import { splitByKind, titlesOf, type UnitCard } from "./apps/lib";

const CATALOG = ["units-catalog"];

/** Apps & plugins: switch modules and plugins on or off for this business, or delete a switched-off one's data. */
export default function AppsPage() {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const { refresh } = useSession();
  const [pending, setPending] = useState<Pending>();
  const catalog = useQuery({ queryKey: CATALOG, queryFn: () => unwrap(api.GET("/api/v1/units/catalog")) });
  const cards: UnitCard[] = catalog.data ?? [];

  /** After any change: reload the list and the session so menus and routes follow without signing out. */
  const changed = async () => {
    await Promise.all([qc.invalidateQueries({ queryKey: CATALOG }), refresh()]);
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

  const { modules, plugins } = splitByKind(cards);
  const ask = (kind: Pending["kind"], unit: UnitCard) => { mutations[kind].reset(); setPending({ kind, unit }); };
  const section = (title: string, hint: string, icon: JSX.Element, list: UnitCard[]) => list.length > 0 && (
    <section className="mb-8" aria-labelledby={`apps-${title}`}>
      <h2 id={`apps-${title}`} className="flex items-center gap-2 text-base font-semibold">{icon}{title}</h2>
      <p className="mb-3 text-sm text-muted">{hint}</p>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {list.map((u) => <UnitCardView key={u.name} unit={u} all={cards} onEnable={() => ask("enable", u)} onDisable={() => ask("disable", u)} onRemove={() => ask("remove", u)} />)}
      </div>
    </section>
  );

  return (
    <>
      <PageHeader title={t("apps.title")} description={t("apps.hint")} />
      {catalog.isLoading && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" role="status" aria-label="Loading">
          {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-40 rounded-xl" />)}
        </div>
      )}
      {catalog.error && <ErrorState title={t("apps.loadFailed")} message={catalog.error.message} onRetry={() => void catalog.refetch()} />}
      {!catalog.isLoading && !catalog.error && cards.length === 0 && <EmptyState title={t("apps.none")} hint={t("apps.noneHint")} />}
      {section(t("apps.modules"), t("apps.modulesHint"), <Blocks className="h-4 w-4 text-muted" />, modules)}
      {section(t("apps.plugins"), t("apps.pluginsHint"), <Plug className="h-4 w-4 text-muted" />, plugins)}
      <UnitDialogs pending={pending} all={cards} mutations={mutations} onClose={() => setPending(undefined)} />
    </>
  );
}
