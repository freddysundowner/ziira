import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Badge, Button, type BadgeTone, type Column, DataTable, formatDate, Select, toast, useTranslation } from "@/sdk";

import type { PlatformSchema } from "../../types";
import { opApi, opUnwrap } from "../../client";
import { ChangeConfirm } from "../../components/ChangeConfirm";
import { useOperatorCan } from "../../me";
import { useRefreshOperator } from "./invoiceDialogs";

type Request = PlatformSchema<"RequestOut">;
const TONES: Record<string, BadgeTone> = { pending: "warn", approved: "ok", declined: "bad", cancelled: "neutral" };

export default function RequestsTab() {
  const { t } = useTranslation("operator");
  const canBill = useOperatorCan("platform.billing");
  const refresh = useRefreshOperator();
  const [status, setStatus] = useState("pending");
  const [deciding, setDeciding] = useState<{ request: Request; approve: boolean } | null>(null);
  const list = useQuery({
    queryKey: ["operator", "plan-requests", status],
    queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/plan-requests", { params: { query: { status } } })),
  });

  const columns: Column<Request>[] = [
    {
      header: t("billing.requests.subscriber"),
      cell: (r) => (
        <div className="min-w-0">
          <Link className="truncate font-medium hover:underline" to={`/operator/subscribers/${encodeURIComponent(r.tenant_code ?? "")}`}>{r.tenant_name ?? r.tenant_code}</Link>
          <p className="truncate font-mono text-xs text-muted">{r.tenant_code}</p>
        </div>
      ),
    },
    { header: t("billing.requests.plan"), cell: (r) => <div><p className="text-sm">{r.plan_name}</p><p className="text-xs text-muted">{t(`interval.${r.interval}`)} · {r.currency}{r.coupon_code ? ` · ${r.coupon_code}` : ""}</p></div> },
    { header: t("billing.requests.note"), hideBelow: "md", cell: (r) => <span className="text-xs text-muted">{r.note}</span> },
    { header: t("billing.requests.requested"), hideBelow: "sm", cell: (r) => <div><p className="text-sm">{formatDate(r.created_at)}</p><p className="text-xs text-muted">{r.requested_by}</p></div> },
    { header: t("billing.invoice.status"), cell: (r) => <Badge tone={TONES[r.status] ?? "neutral"}>{t(`billing.requests.statuses.${r.status}`, r.status)}</Badge> },
    {
      header: "", align: "right",
      cell: (r) => r.status === "pending" && canBill ? (
        <div className="flex justify-end gap-1.5">
          <Button size="sm" onClick={() => setDeciding({ request: r, approve: true })}>{t("billing.requests.approve")}</Button>
          <Button size="sm" variant="secondary" onClick={() => setDeciding({ request: r, approve: false })}>{t("billing.requests.decline")}</Button>
        </div>
      ) : null,
    },
  ];

  return (
    <>
      <DataTable
        rows={list.data}
        columns={columns}
        rowKey={(r) => r.id}
        loading={list.isPending}
        error={list.isError ? list.error.message : null}
        onRetry={() => void list.refetch()}
        pageSize={25}
        empty={{ title: t(`billing.requests.empty.${status}`, t("billing.requests.emptyOther")), hint: status === "pending" ? t("billing.requests.emptyHint") : undefined }}
        toolbar={(
          <Select aria-label={t("billing.requests.filterStatus")} value={status} onChange={(e) => setStatus(e.target.value)} className="w-44">
            {["pending", "approved", "declined", "cancelled"].map((s) => <option key={s} value={s}>{t(`billing.requests.statuses.${s}`)}</option>)}
          </Select>
        )}
      />
      {deciding && (
        <ChangeConfirm
          title={t(deciding.approve ? "billing.requests.approveTitle" : "billing.requests.declineTitle", { name: deciding.request.tenant_name ?? deciding.request.tenant_code })}
          message={<p>{t(deciding.approve ? "billing.requests.approveMessage" : "billing.requests.declineMessage", { plan: deciding.request.plan_name })}</p>}
          confirmLabel={t(deciding.approve ? "billing.requests.approve" : "billing.requests.decline")}
          danger={!deciding.approve}
          run={() => opUnwrap(opApi.POST("/api/v1/operator/plan-requests/{request_id}/decide", { params: { path: { request_id: deciding.request.id } }, body: { approve: deciding.approve } }))}
          onDone={(result) => { toast(result.invoice?.number ? t("billing.requests.decidedInvoice", { number: result.invoice.number }) : t("billing.requests.decided"), "ok"); refresh(); }}
          onClose={() => setDeciding(null)}
        />
      )}
    </>
  );
}
