import { ArrowLeftRight, Plus } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, DataTable, formatDate, Input, Menu, PageHeader, Pager, Select, StatusBadge, Stat, unwrap, useCan, useCompany, usePagedList,
  useTranslation, type Schemas,
} from "@/sdk";

import { Amount } from "../components/Amount";
import { MoveMoney, type MoveKind } from "../components/MoveMoney";
import { PaymentDetail } from "../components/PaymentDetail";
import { METHODS, RecordPayment } from "../components/RecordPayment";
import { usePaymentAccounts } from "../components/usePaymentAccounts";
import { summarise } from "../logic";

/** Every payment received or paid out, newest first, with filters, a form to record one and a detail view with reversal. */
export default function PaymentsPage() {
  const { t } = useTranslation("payments");
  const canRecord = useCan("payments.record");
  const { company } = useCompany();
  const [method, setMethod] = useState("");
  const [date, setDate] = useState("");
  const [reference, setReference] = useState("");
  const [recording, setRecording] = useState(false);
  const [moving, setMoving] = useState<MoveKind | null>(null);
  const [selected, setSelected] = useState<Schemas["PaymentOut"] | null>(null);
  const accounts = usePaymentAccounts({ includeInactive: true });
  const filtered = !!(method || date || reference.trim());
  const list = usePagedList(["payments", method, date, reference.trim()], (limit, offset) =>
    unwrap(api.GET("/api/v1/payments/payments", { params: { query: { method: method || undefined, business_date: date || undefined, external_ref: reference.trim() || undefined, limit, offset } } })));
  const shown = summarise(list.rows ?? []);

  return (
    <>
      <PageHeader title={t("title")} description={t("hint")}
        actions={canRecord && (
          <>
            <Menu label={t("moveMoney")} trigger={<span className="inline-flex items-center gap-2"><ArrowLeftRight className="h-4 w-4" />{t("moveMoney")}</span>}
              items={[{ label: t("settlement"), onSelect: () => setMoving("settlement") }, { label: t("cashDeposit"), onSelect: () => setMoving("deposit") }]} />
            <Button onClick={() => setRecording(true)}><Plus className="h-4 w-4" />{t("recordPayment")}</Button>
          </>
        )} />
      {list.rows && list.rows.length > 0 && (
        <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-3">
          <Stat label={t("receivedOnPage")} value={<Amount value={shown.received} companyId={company?.id} />} tone="ok" />
          <Stat label={t("paidOutOnPage")} value={<Amount value={shown.paidOut} companyId={company?.id} />} />
          <Stat label={t("paymentsOnPage")} value={shown.count} hint={t("onThisPage")} />
        </div>
      )}
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(p) => p.id}
        toolbar={
          <>
            <Select className="w-44" aria-label={t("method")} value={method} onChange={(e) => setMethod(e.target.value)}>
              <option value="">{t("allMethods")}</option>{METHODS.map((m) => <option key={m} value={m}>{t(`methods.${m}`)}</option>)}
            </Select>
            <Input type="date" className="w-40" aria-label={t("date")} value={date} onChange={(e) => setDate(e.target.value)} />
            <Input className="w-44" aria-label={t("reference")} placeholder={t("reference")} value={reference} onChange={(e) => setReference(e.target.value)} />
          </>
        }
        empty={{ title: filtered ? t("noMatch") : t("empty"), hint: filtered ? undefined : t("emptyHint"), action: canRecord && !filtered ? <Button onClick={() => setRecording(true)}>{t("recordPayment")}</Button> : undefined }}
        columns={[
          { header: t("number"), cell: (p) => <button className="font-mono text-xs font-medium hover:underline" onClick={() => setSelected(p)}>{p.number}</button> },
          { header: t("date"), cell: (p) => formatDate(p.business_date) },
          { header: t("method"), hideBelow: "sm", cell: (p) => t(`methods.${p.method}`, p.method) },
          { header: t("account"), hideBelow: "lg", cell: (p) => accounts.data?.find((a) => a.id === p.payment_account_id)?.name ?? "—" },
          { header: t("reference"), hideBelow: "md", cell: (p) => <span className="font-mono text-xs">{p.external_ref ?? "—"}</span> },
          { header: t("party"), hideBelow: "lg", cell: (p) => (p.party_type ? <Badge>{t(`parties.${p.party_type}`, p.party_type)}</Badge> : "—") },
          {
            header: t("amount"), align: "right",
            cell: (p) => <span className={p.direction === "out" ? "font-medium text-warn" : "font-medium"}>{p.direction === "out" ? "−" : ""}<Amount value={p.amount} companyId={p.company_id} /></span>,
          },
          { header: t("status"), cell: (p) => <StatusBadge status={p.status} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <RecordPayment open={recording} onClose={() => setRecording(false)} />
      <MoveMoney kind={moving} onClose={() => setMoving(null)} />
      <PaymentDetail payment={selected} onClose={() => setSelected(null)} />
    </>
  );
}
