import { MoreHorizontal, Plus } from "lucide-react";
import { useState } from "react";

import {
  Alert, api, Badge, Button, ConfirmDialog, DataTable, formatDate, Menu, PageHeader, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation, type MenuEntry, type Schemas,
} from "@/sdk";

import DeliveriesDrawer from "./webhooks/DeliveriesDrawer";
import EndpointDrawer from "./webhooks/EndpointDrawer";
import { endpointTone, eventSummary } from "./webhooks/lib";
import SecretReveal from "./webhooks/SecretReveal";

type Endpoint = Schemas["WebhookOut"];

/** Settings > Webhooks: web addresses of this business that are told when chosen things happen. */
export default function WebhooksPage() {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [editing, setEditing] = useState<Endpoint | null | "new">(null);
  const [viewing, setViewing] = useState<Endpoint | null>(null);
  const [deleting, setDeleting] = useState<Endpoint | null>(null);
  const [secret, setSecret] = useState<{ name: string; value: string } | null>(null);
  const list = useQuery({ queryKey: ["webhooks"], queryFn: () => unwrap(api.GET("/api/v1/webhooks/endpoints")) });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["webhooks"] });
  const path = (e: Endpoint) => ({ params: { path: { endpoint_id: e.id } } });

  const ping = useMutation({
    mutationFn: (e: Endpoint) => unwrap(api.POST("/api/v1/webhooks/endpoints/{endpoint_id}/ping", path(e))),
    onSuccess: (_, e) => { toast(t("webhooks.testQueued"), "ok"); setViewing(e); },
  });
  const setStatus = useMutation({
    mutationFn: ({ e, status }: { e: Endpoint; status: "active" | "paused" }) => unwrap(api.PATCH("/api/v1/webhooks/endpoints/{endpoint_id}", { ...path(e), body: { status } })),
    onSuccess: refresh,
  });
  const newSecret = useMutation({
    mutationFn: (e: Endpoint) => unwrap(api.POST("/api/v1/webhooks/endpoints/{endpoint_id}/secret", path(e))).then((r) => ({ name: e.name, value: r.secret })),
    onSuccess: (s) => { setSecret(s); refresh(); },
  });
  const remove = useMutation({
    mutationFn: (e: Endpoint) => unwrap(api.DELETE("/api/v1/webhooks/endpoints/{endpoint_id}", path(e))),
    onSuccess: () => { refresh(); toast(t("webhooks.deleted"), "ok"); setDeleting(null); },
  });

  const actions = (e: Endpoint): (MenuEntry | "separator")[] => [
    { label: t("webhooks.deliveries"), onSelect: () => setViewing(e) },
    { label: t("webhooks.sendTest"), onSelect: () => ping.mutate(e), disabled: e.status === "disabled" },
    { label: t("webhooks.edit"), onSelect: () => setEditing(e) },
    e.status === "active" ? { label: t("webhooks.pause"), onSelect: () => setStatus.mutate({ e, status: "paused" }) }
      : { label: e.status === "disabled" ? t("webhooks.enable") : t("webhooks.resume"), onSelect: () => setStatus.mutate({ e, status: "active" }) },
    { label: t("webhooks.newSecret"), onSelect: () => newSecret.mutate(e) },
    "separator",
    { label: t("webhooks.delete"), danger: true, onSelect: () => setDeleting(e) },
  ];

  return (
    <>
      <PageHeader title={t("webhooks.title")} description={t("webhooks.hint")} actions={<Button onClick={() => setEditing("new")}><Plus className="h-4 w-4" />{t("webhooks.new")}</Button>} />
      <DataTable
        rows={list.data} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()} rowKey={(e) => e.id}
        searchText={(e) => `${e.name} ${e.url}`} searchPlaceholder={t("webhooks.search")}
        empty={{ title: t("webhooks.none"), hint: t("webhooks.noneHint"), action: <Button onClick={() => setEditing("new")}>{t("webhooks.new")}</Button> }}
        columns={[
          { header: t("webhooks.name"), sortValue: (e) => e.name, cell: (e) => (
            <div className="min-w-0"><p className="font-medium">{e.name}</p><p className="max-w-xs truncate text-xs text-muted">{e.url}</p>
              {e.disabled_reason && <p className="mt-1 text-xs text-bad">{e.disabled_reason}</p>}</div>) },
          { header: t("webhooks.events"), hideBelow: "lg", cell: (e) => <span className="text-xs text-muted">{eventSummary(e.event_types)}</span> },
          { header: t("webhooks.state"), cell: (e) => (
            <div className="space-y-1"><Badge tone={endpointTone(e)}>{t(`webhooks.endpointStatus.${e.status}`)}</Badge>
              {e.consecutive_failures > 0 && <p className="text-xs text-warn">{t("webhooks.failures", { count: e.consecutive_failures })}</p>}</div>) },
          { header: t("webhooks.lastSuccess"), hideBelow: "md", cell: (e) => (e.last_success_at ? formatDate(e.last_success_at, true) : "—") },
          { header: "", align: "right", cell: (e) => <Menu label={t("webhooks.actions", { name: e.name })} trigger={<MoreHorizontal className="h-4 w-4" />} items={actions(e)} /> },
        ]}
      />
      <Alert tone="info" className="mt-4">{t("webhooks.docsNote")}</Alert>
      <EndpointDrawer open={editing !== null} endpoint={editing === "new" ? null : editing} onClose={() => setEditing(null)}
        onCreated={(name, value) => { setEditing(null); setSecret({ name, value }); }} />
      <DeliveriesDrawer endpoint={viewing} onClose={() => setViewing(null)} />
      <SecretReveal secret={secret} onClose={() => setSecret(null)} />
      <ConfirmDialog open={!!deleting} onClose={() => setDeleting(null)} danger busy={remove.isPending} title={t("webhooks.delete")} confirmLabel={t("webhooks.delete")}
        message={t("webhooks.deleteAsk", { name: deleting?.name })} onConfirm={() => deleting && remove.mutate(deleting)} />
    </>
  );
}
