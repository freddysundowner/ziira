import { useState } from "react";

import {
  api, Button, Card, DataTable, Field, formatDate, Input, Modal, money, Pager, StatusBadge, Stat, Tabs, Textarea, today, toast, unwrap, useCurrency, useFormState,
  useMutation, usePagedList, useQuery, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

import { isPositive, overdueOf } from "../logic";
import { Amount } from "./Amount";
import { useReceivables } from "./useReceivables";

type Customer = Schemas["CustomerOut"];

/** What a customer owes (from Point of sale's invoices and receipts): balance, statement, invoices and payments received. */
export function AccountTab({ customer }: { customer: Customer }) {
  const { t } = useTranslation("crm");
  const [part, setPart] = useState<"statement" | "invoices" | "receipts">("statement");
  const id = customer.id;
  const balance = useQuery({ queryKey: ["customer-balance", id], queryFn: () => unwrap(api.GET("/api/v1/pos/customers/{customer_id}/balance", { params: { path: { customer_id: id } } })) });
  const ageing = useQuery({ queryKey: ["ageing", id], queryFn: () => unwrap(api.GET("/api/v1/pos/receivables/ageing", { params: { query: { customer_id: id } } })) });
  const b = balance.data;
  const currency = useCurrency(customer.company_id);
  const overdue = ageing.data ? overdueOf(ageing.data.buckets) : undefined;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label={t("owes")} loading={balance.isLoading} value={b ? <Amount value={b.owes} companyId={customer.company_id} /> : "—"} tone={b && isPositive(b.owes) ? "bad" : undefined}
          hint={b && isPositive(b.credit_on_account) ? t("creditOnAccount", { amount: money(b.credit_on_account, currency) }) : undefined} />
        <Stat label={t("overdue")} loading={ageing.isLoading} value={overdue !== undefined ? <Amount value={overdue} companyId={customer.company_id} /> : "—"} tone={overdue && isPositive(overdue) ? "bad" : undefined} />
        <Stat label={t("creditLimit")} loading={balance.isLoading} value={b ? <Amount value={b.credit_limit} companyId={customer.company_id} /> : "—"} />
        <Stat label={t("availableCredit")} loading={balance.isLoading} value={b ? <Amount value={b.available} companyId={customer.company_id} /> : "—"} />
      </div>
      {(balance.error || ageing.error) && <p className="text-sm text-bad">{(balance.error ?? ageing.error)?.message}</p>}
      {ageing.data && <AgeingStrip customer={customer} buckets={ageing.data.buckets} />}
      <Tabs value={part} onChange={setPart} tabs={[{ id: "statement", label: t("statement") }, { id: "invoices", label: t("invoices") }, { id: "receipts", label: t("receipts") }]} />
      {part === "statement" && <Statement customer={customer} />}
      {part === "invoices" && <Invoices customer={customer} />}
      {part === "receipts" && <Receipts customer={customer} />}
    </div>
  );
}

const BUCKET_KEYS = ["not_due", "1_30", "31_60", "61_90", "over_90"] as const;

export function AgeingStrip({ customer, buckets }: { customer?: Customer; buckets: Record<string, string> }) {
  const { t } = useTranslation("crm");
  return (
    <Card title={t("ageing")}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {BUCKET_KEYS.map((k) => (
          <div key={k}>
            <p className="text-xs text-muted">{t(`buckets.${k}`)}</p>
            <p className="tnum text-sm font-semibold"><Amount value={buckets[k]} companyId={customer?.company_id} /></p>
          </div>
        ))}
      </div>
    </Card>
  );
}

function Statement({ customer }: { customer: Customer }) {
  const { t } = useTranslation("crm");
  const f = useFormState({ from: "", to: "" });
  const q = useQuery({
    queryKey: ["customer-statement", customer.id, f.values.from, f.values.to],
    queryFn: () => unwrap(api.GET("/api/v1/pos/customers/{customer_id}/statement", { params: { path: { customer_id: customer.id }, query: { date_from: f.values.from || undefined, date_to: f.values.to || undefined } } })),
  });
  const s = q.data;
  return (
    <DataTable
      rows={s?.lines} loading={q.isLoading} error={q.error?.message} onRetry={() => void q.refetch()} rowKey={(l) => `${l.kind}-${l.number}`}
      toolbar={
        <div className="flex flex-wrap items-center gap-2">
          <Input type="date" aria-label={t("from")} className="w-40" max={today()} {...f.bind("from")} />
          <Input type="date" aria-label={t("to")} className="w-40" max={today()} {...f.bind("to")} />
          {s && <span className="text-xs text-muted">{t("openingBalance")}: <Amount value={s.opening_balance} companyId={customer.company_id} /></span>}
        </div>
      }
      empty={{ title: t("noStatement"), hint: t("noStatementHint") }}
      columns={[
        { header: t("date"), cell: (l) => formatDate(l.date) },
        { header: t("number"), cell: (l) => <span className="font-mono text-xs">{l.number}</span> },
        { header: t("kindDoc"), hideBelow: "sm", cell: (l) => t(`docKinds.${l.kind}`, l.kind) },
        { header: t("description"), hideBelow: "lg", cell: (l) => l.description },
        { header: t("debit"), align: "right", hideBelow: "sm", cell: (l) => (isPositive(l.debit) ? <Amount value={l.debit} companyId={customer.company_id} /> : "") },
        { header: t("creditCol"), align: "right", hideBelow: "sm", cell: (l) => (isPositive(l.credit) ? <Amount value={l.credit} companyId={customer.company_id} /> : "") },
        { header: t("balance"), align: "right", cell: (l) => <span className="font-medium"><Amount value={l.balance} companyId={customer.company_id} /></span> },
      ]}
      footer={s && <div className="flex justify-between border-t border-line px-4 py-2 text-sm"><span className="text-muted">{t("closingBalance")}</span><span className="tnum font-semibold"><Amount value={s.closing_balance} companyId={customer.company_id} /></span></div>}
    />
  );
}

function Invoices({ customer }: { customer: Customer }) {
  const { t } = useTranslation("crm");
  const list = usePagedList(["customer-invoices", customer.id], (limit, offset) =>
    unwrap(api.GET("/api/v1/pos/invoices", { params: { query: { customer_id: customer.id, limit, offset } } })));
  return (
    <DataTable
      rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(i) => i.id}
      empty={{ title: t("noInvoices"), hint: t("noInvoicesHint") }}
      columns={[
        { header: t("number"), cell: (i) => <span className="font-mono text-xs font-medium">{i.number}</span> },
        { header: t("issued"), hideBelow: "sm", cell: (i) => formatDate(i.issue_date) },
        { header: t("dueDate"), cell: (i) => formatDate(i.due_date) },
        { header: t("total"), align: "right", cell: (i) => <Amount value={i.total} companyId={i.company_id} /> },
        { header: t("paid"), align: "right", hideBelow: "md", cell: (i) => <Amount value={i.amount_paid} companyId={i.company_id} /> },
        { header: t("status"), cell: (i) => <StatusBadge status={i.status} /> },
      ]}
      footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
    />
  );
}

function Receipts({ customer }: { customer: Customer }) {
  const { t } = useTranslation("crm");
  const qc = useQueryClient();
  const { canReceive } = useReceivables();
  const [reversing, setReversing] = useState<{ id: string; number: string } | null>(null);
  const [reason, setReason] = useState("");
  const list = usePagedList(["customer-receipts", customer.id], (limit, offset) =>
    unwrap(api.GET("/api/v1/pos/receipts", { params: { query: { customer_id: customer.id, limit, offset } } })));
  const reverse = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/pos/receipts/{receipt_id}/reverse", { params: { path: { receipt_id: reversing?.id ?? "" } }, body: { reason: reason.trim() } })),
    onSuccess: () => {
      for (const key of ["customer-balance", "customer-statement", "customer-receipts", "customer-invoices", "ageing"]) void qc.invalidateQueries({ queryKey: [key] });
      toast(t("receiptReversed"), "ok");
      setReversing(null); setReason("");
    },
  });
  return (
    <>
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(r) => r.id}
        empty={{ title: t("noReceipts"), hint: t("noReceiptsHint") }}
        columns={[
          { header: t("number"), cell: (r) => <span className="font-mono text-xs font-medium">{r.number}</span> },
          { header: t("date"), cell: (r) => formatDate(r.received_on) },
          { header: t("method"), hideBelow: "sm", cell: (r) => t(`methods.${r.method}`, r.method) },
          { header: t("reference"), hideBelow: "lg", cell: (r) => r.reference ?? "—" },
          { header: t("amount"), align: "right", cell: (r) => <Amount value={r.amount} companyId={r.company_id} /> },
          { header: t("unallocated"), align: "right", hideBelow: "md", cell: (r) => (isPositive(r.unallocated) ? <Amount value={r.unallocated} companyId={r.company_id} /> : "—") },
          { header: t("status"), cell: (r) => <StatusBadge status={r.status} /> },
          { header: "", align: "right", cell: (r) => canReceive && r.status !== "reversed" && <Button size="sm" variant="ghost" onClick={() => setReversing({ id: r.id, number: r.number })}>{t("reverse")}</Button> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <Modal open={!!reversing} onClose={() => setReversing(null)} title={t("reverseReceipt")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setReversing(null)}>{t("cancel")}</Button><Button variant="danger" loading={reverse.isPending} disabled={!reason.trim()} onClick={() => reverse.mutate()}>{t("reverse")}</Button></>}>
        <p className="mb-3 text-sm text-muted">{t("reverseAsk", { number: reversing?.number })}</p>
        <Field label={t("reason")} required><Textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} /></Field>
      </Modal>
    </>
  );
}
