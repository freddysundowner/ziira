import { Pencil, Trash2 } from "lucide-react";

import { api, Badge, Button, DataTable, formatDate, IconButton, money, today, unwrap, useQuery, useTranslation } from "@/sdk";

import { useStaff } from "../hooks";
import type { Client, Rate } from "../types";

/** What a rate row covers, in words: the project, client, person, service or role it names (or everything). */
function Covers({ rate, companyId, clients }: { rate: Rate; companyId: string; clients: readonly Client[] | undefined }) {
  const { t } = useTranslation("timebilling");
  const staff = useStaff(companyId);
  const project = useQuery({
    queryKey: ["timebilling", "project", rate.project_id], enabled: !!rate.project_id, staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/projects/{project_id}", { params: { path: { project_id: rate.project_id! } } })),
  });
  const service = useQuery({
    queryKey: ["timebilling", "service-item", rate.service_product_id], enabled: !!rate.service_product_id, staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/products/products/{product_id}", { params: { path: { product_id: rate.service_product_id! } } })),
  });
  const tags: { label: string; value: string }[] = [];
  if (rate.project_id) tags.push({ label: t("projectField"), value: project.data ? `${project.data.code} · ${project.data.name}` : "…" });
  if (rate.client_id) tags.push({ label: t("client"), value: clients?.find((c) => c.customer_id === rate.client_id)?.name ?? "…" });
  if (rate.user_id) tags.push({ label: t("rates.person"), value: staff.data?.find((s) => s.user_id === rate.user_id)?.name ?? "…" });
  if (rate.service_product_id) tags.push({ label: t("projects.serviceItem"), value: service.data?.name ?? "…" });
  if (rate.role_title) tags.push({ label: t("rates.role"), value: rate.role_title });
  if (tags.length === 0) return <span className="text-muted">{t("rates.everything")}</span>;
  return <span className="flex max-w-[16rem] flex-wrap gap-1">{tags.map((x) => <span key={x.label} className="rounded-lg bg-brand-soft px-2 py-0.5 text-xs font-medium text-brand-strong">{x.label}: {x.value}</span>)}</span>;
}

/** The rows of one rate card (bill or cost). */
export function RateTable({ rates, loading, error, onRetry, companyId, clients, currency, onEdit, onEnd, onDelete, onConfirm, empty }: {
  rates: readonly Rate[] | undefined; loading: boolean; error?: string | null; onRetry: () => void; companyId: string; clients: readonly Client[] | undefined; currency?: string;
  onEdit: (r: Rate) => void; onEnd: (r: Rate) => void; onDelete: (r: Rate) => void; onConfirm?: (r: Rate) => void; empty: { title: string; hint?: string };
}) {
  const { t } = useTranslation("timebilling");
  const now = today();
  return (
    <DataTable
      rows={rates} loading={loading} error={error} onRetry={onRetry} rowKey={(r) => r.id} empty={empty}
      columns={[
        { header: t("rates.covers"), cell: (r) => <Covers rate={r} companyId={companyId} clients={clients} /> },
        { header: t("rates.perHour"), align: "right", sortValue: (r) => Number(r.rate), cell: (r) => <span className="tnum font-medium">{money(r.rate, currency)}</span> },
        { header: t("rates.from"), hideBelow: "sm", sortValue: (r) => r.effective_from, cell: (r) => formatDate(r.effective_from) },
        { header: t("rates.to"), hideBelow: "sm", cell: (r) => (r.effective_to ? formatDate(r.effective_to) : <span className="text-muted">{t("rates.open")}</span>) },
        { header: t("status"), hideBelow: "md", cell: (r) => (r.example ? <Badge tone="warn">{t("rates.example")}</Badge> : r.effective_from > now ? <Badge tone="info">{t("rates.upcoming")}</Badge> : r.effective_to && r.effective_to < now ? <Badge>{t("rates.ended")}</Badge> : <Badge tone="ok">{t("rates.inForce")}</Badge>) },
        {
          header: "", align: "right",
          cell: (r) => (
            <span className="flex justify-end gap-1">
              {r.example && onConfirm && <Button size="sm" variant="secondary" onClick={() => onConfirm(r)}>{t("rates.useExample")}</Button>}
              {!r.example && (!r.effective_to || r.effective_to >= now) && <Button size="sm" variant="ghost" onClick={() => onEnd(r)}>{t("rates.endToday")}</Button>}
              <IconButton label={t("edit")} onClick={() => onEdit(r)}><Pencil className="h-4 w-4" /></IconButton>
              <IconButton label={t("delete")} onClick={() => onDelete(r)}><Trash2 className="h-4 w-4" /></IconButton>
            </span>
          ),
        },
      ]} />
  );
}
