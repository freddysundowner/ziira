import { Plus } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Button, type Column, DataTable, formatDate, Input, money, Pager, Select, usePagedList, useDebounced, useTranslation } from "@/sdk";

import type { PlatformSchema } from "../../types";
import { opApi, opUnwrap } from "../../client";
import { InvoiceBadge } from "../../components/bits";
import { useOperatorCan } from "../../me";
import { InvoiceDrawer } from "./InvoiceDrawer";
import { InvoiceFormDialog, invoiceTarget } from "./invoiceDialogs";

type Invoice = PlatformSchema<"InvoiceOut">;
const STATUSES = ["draft", "issued", "paid", "void"];
const PAGE = 25;

export default function InvoicesTab() {
  const { t } = useTranslation("operator");
  const canBill = useOperatorCan("platform.billing");
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const [typed, setTyped] = useState(params.get("subscriber") ?? "");
  const subscriber = useDebounced(typed.trim().toLowerCase());
  const [open, setOpen] = useState<string | null>(params.get("open"));
  const [creating, setCreating] = useState(params.get("new") === "1" && canBill);

  const list = usePagedList<Invoice>(["operator", "invoices", status, subscriber], (limit, offset) =>
    opUnwrap(opApi.GET("/api/v1/operator/invoices", { params: { query: { limit, offset, ...(status ? { status } : {}), ...(subscriber ? { tenant_code: subscriber } : {}) } } })), PAGE);

  const columns: Column<Invoice>[] = [
    { header: t("billing.invoice.number"), cell: (i) => (
      <button type="button" onClick={() => setOpen(i.id)} className="rounded font-mono text-sm font-medium text-brand-strong hover:underline" aria-label={t("billing.invoices.open", { number: i.number ?? t("billing.invoice.draftTitle") })}>
        {i.number ?? t("billing.invoice.draftTitle")}
      </button>
    ) },
    { header: t("billing.invoice.billTo"), cell: (i) => <div className="min-w-0"><p className="truncate text-sm font-medium">{invoiceTarget(i)}</p>{i.tenant_code && <p className="truncate font-mono text-xs text-muted">{i.tenant_code}</p>}</div> },
    { header: t("billing.invoice.status"), cell: (i) => <InvoiceBadge status={i.status} /> },
    { header: t("billing.invoice.kind"), hideBelow: "lg", cell: (i) => <span className="text-sm">{t(`billing.invoice.kinds.${i.kind}`, i.kind)}</span> },
    { header: t("billing.invoice.total"), align: "right", cell: (i) => <span className="text-sm">{money(i.total, i.currency)}</span> },
    { header: t("billing.invoice.balance"), align: "right", hideBelow: "sm", cell: (i) => <span className={Number(i.balance) > 0 && i.status === "issued" ? "text-sm text-bad" : "text-sm text-muted"}>{money(i.balance, i.currency)}</span> },
    { header: t("billing.invoice.dueDate"), hideBelow: "md", cell: (i) => <span className="text-sm">{i.due_date ? formatDate(i.due_date) : "-"}</span> },
  ];

  return (
    <>
      <DataTable
        rows={list.rows}
        columns={columns}
        rowKey={(i) => i.id}
        loading={list.query.isPending}
        error={list.query.isError ? list.query.error.message : null}
        onRetry={() => void list.query.refetch()}
        empty={{ title: status || subscriber ? t("billing.invoices.noMatch") : t("billing.invoices.empty"), hint: t("billing.invoices.emptyHint") }}
        toolbar={(
          <>
            <Select aria-label={t("billing.invoices.filterStatus")} value={status} className="w-40"
              onChange={(e) => { const next = new URLSearchParams(params); if (e.target.value) next.set("status", e.target.value); else next.delete("status"); setParams(next, { replace: true }); }}>
              <option value="">{t("billing.invoices.allStatuses")}</option>
              {STATUSES.map((s) => <option key={s} value={s}>{t(`invoiceStatus.${s}`)}</option>)}
            </Select>
            <Input aria-label={t("billing.invoices.filterSubscriber")} placeholder={t("billing.invoices.filterSubscriber")} value={typed} onChange={(e) => setTyped(e.target.value)} className="w-52 font-mono" />
            {canBill && <Button className="ml-auto" size="sm" onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> {t("billing.invoices.new")}</Button>}
          </>
        )}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      {open && <InvoiceDrawer invoiceId={open} onClose={() => setOpen(null)} />}
      {creating && <InvoiceFormDialog onClose={() => setCreating(false)} />}
    </>
  );
}
