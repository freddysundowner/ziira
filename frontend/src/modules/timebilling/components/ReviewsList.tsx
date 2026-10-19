import { api, Badge, type BadgeTone, DataTable, formatDate, money, unwrap, useQuery, useTranslation } from "@/sdk";

import type { Client } from "../types";

const TONE: Record<string, BadgeTone> = { draft: "warn", issued: "ok", cancelled: "bad", discarded: "neutral" };

/** Invoice reviews already started, drafts first. */
export function ReviewsList({ companyId, clients, currency }: { companyId: string; clients: readonly Client[] | undefined; currency?: string }) {
  const { t } = useTranslation("timebilling");
  const list = useQuery({
    queryKey: ["timebilling", "reviews", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/invoice-reviews", { params: { query: { company_id: companyId, limit: 50 } } })),
  });
  const rows = list.data && [...list.data].sort((a, b) => Number(b.status === "draft") - Number(a.status === "draft") || b.created_at.localeCompare(a.created_at));
  const name = (id: string) => clients?.find((c) => c.customer_id === id)?.name ?? "—";
  return (
    <DataTable
      rows={rows} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()} rowKey={(r) => r.id} rowHref={(r) => `/time/reviews/${r.id}`}
      empty={{ title: t("reviews.empty"), hint: t("reviews.emptyHint") }}
      columns={[
        { header: t("client"), cell: (r) => <span className="font-medium">{name(r.client_id)}</span> },
        { header: t("date"), hideBelow: "sm", cell: (r) => formatDate(r.created_at) },
        { header: t("reviews.invoice"), hideBelow: "md", cell: (r) => r.invoice_number ?? "—" },
        { header: t("reviews.memo"), hideBelow: "lg", cell: (r) => r.memo ?? "—" },
        { header: t("reviews.total"), align: "right", cell: (r) => (r.total ? <span className="tnum">{money(r.total, currency)}</span> : "—") },
        { header: t("status"), cell: (r) => <span className="flex flex-wrap gap-1"><Badge tone={TONE[r.status] ?? "neutral"}>{t(`reviews.status.${r.status}`, r.status)}</Badge>{r.status === "draft" && r.review_status === "requested" && <Badge tone="warn">{t("partner.status.requested")}</Badge>}{r.status === "draft" && r.review_status === "approved" && <Badge tone="ok">{t("partner.status.approved")}</Badge>}</span> },
      ]} />
  );
}
