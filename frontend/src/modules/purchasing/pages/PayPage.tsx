import { type FormEvent, useState } from "react";

import {
  Alert, api, Button, Card, Checkbox, ConfirmDialog, DataTable, Field, FormGrid, formatDate, Input, money, NumberInput, PageHeader, Select, toast, today, unwrap,
  useCurrency, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { Money } from "../components/Money";
import { SupplierPicker } from "../components/pickers";
import { Status } from "../components/Status";
import { useSupplier, usePaymentAccounts } from "../hooks";
import { allocateOldestFirst, amountDue, isOpenBill, isOverdue, PAY_METHODS, sumAmounts } from "../lib";
import type { BillSummary, PayMethod } from "../types";

/** Pay one supplier: tick the bills, set the amounts (or spread one payment oldest first) and pay them together. */
export default function PayPage() {
  const { t } = useTranslation("purchasing");
  const qc = useQueryClient();
  const [supplierId, setSupplierId] = useState("");
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [lump, setLump] = useState("");
  const [method, setMethod] = useState<PayMethod>("bank");
  const [account, setAccount] = useState("");
  const [reference, setReference] = useState("");
  const [date, setDate] = useState(today());
  const [confirming, setConfirming] = useState(false);
  const [results, setResults] = useState<Record<string, string>>({});
  const supplier = useSupplier(supplierId || null);
  const currency = useCurrency(supplier.data?.company_id);
  const accounts = usePaymentAccounts(supplier.data?.company_id);
  const bills = useQuery({
    enabled: !!supplierId, queryKey: ["purchasing", "bills", "open", supplierId],
    queryFn: async () => (await unwrap(api.GET("/api/v1/purchasing/bills", { params: { query: { supplier_id: supplierId, limit: 200 } } }))).filter((b) => isOpenBill(b.status)),
  });
  const rows = (bills.data ?? []).map((b) => ({ ...b, due: amountDue(b) })).sort((a, b) => a.due_date.localeCompare(b.due_date));
  const chosen = rows.filter((b) => Number(amounts[b.id]) > 0);
  const total = sumAmounts(chosen.map((b) => amounts[b.id] ?? "0"));
  const day = today();

  const pay = useMutation({
    meta: { silent: true },
    mutationFn: async () => {
      const out: Record<string, string> = {};
      for (const b of chosen) {
        try {
          await unwrap(api.POST("/api/v1/purchasing/bills/{bill_id}/pay", { params: { path: { bill_id: b.id } }, body: { amount: amounts[b.id] ?? "0", method, payment_account_id: account || null, external_ref: reference.trim() || null, paid_on: date } }));
          out[b.id] = "ok";
        } catch (e) {
          out[b.id] = (e as Error).message;
          break;
        }
      }
      return out;
    },
    onSuccess: (out) => {
      setResults(out);
      setConfirming(false);
      void qc.invalidateQueries({ queryKey: ["purchasing"] });
      const paid = Object.keys(out).filter((id) => out[id] === "ok");
      setAmounts((a) => Object.fromEntries(Object.entries(a).filter(([id]) => !paid.includes(id))));
      toast(t(paid.length === chosen.length ? "paymentsDone" : "paymentsStopped", { count: paid.length }), paid.length === chosen.length ? "ok" : "bad");
    },
  });

  const toggle = (b: BillSummary & { due: string }, on: boolean) => setAmounts((a) => ({ ...a, [b.id]: on ? b.due : "" }));
  const submit = (e: FormEvent) => { e.preventDefault(); setConfirming(true); };

  return (
    <form onSubmit={submit}>
      <PageHeader title={t("paySuppliers")} description={t("paySuppliersHint")} actions={<Button type="submit" disabled={chosen.length === 0 || pay.isPending}>{t("payTotal", { total: money(total, currency) })}</Button>} />
      <div className="space-y-4">
        <Card>
          <FormGrid cols={3}>
            <Field label={t("supplier")} required><SupplierPicker value={supplierId} onChange={(v) => { setSupplierId(v); setAmounts({}); setResults({}); }} /></Field>
            <Field label={t("method")}><Select value={method} onChange={(e) => setMethod(e.target.value as PayMethod)}>{PAY_METHODS.map((m) => <option key={m} value={m}>{t(`methods.${m}`)}</option>)}</Select></Field>
            {(accounts.data?.length ?? 0) > 0 && (
              <Field label={t("fromAccount")}><Select value={account} onChange={(e) => setAccount(e.target.value)}><option value="">{t("noAccount")}</option>{accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>
            )}
            <Field label={t("paidOn")}><Input type="date" max={day} value={date} onChange={(e) => setDate(e.target.value)} /></Field>
            <Field label={t("reference")} hint={t("referenceHint")}><Input value={reference} maxLength={60} onChange={(e) => setReference(e.target.value)} /></Field>
            <Field label={t("spreadPayment")} hint={t("spreadHint")}>
              <div className="flex gap-2">
                <NumberInput value={lump} onChange={setLump} />
                <Button variant="secondary" disabled={!Number(lump) || rows.length === 0} onClick={() => setAmounts(allocateOldestFirst(lump, rows))}>{t("spread")}</Button>
              </div>
            </Field>
          </FormGrid>
        </Card>
        {!supplierId && <Alert tone="info">{t("pickSupplierToPay")}</Alert>}
        {supplierId && (
          <Card title={t("openBills")} flush>
            <DataTable rows={bills.data ? rows : undefined} loading={bills.isLoading} error={bills.error?.message} onRetry={() => void bills.refetch()} rowKey={(b) => b.id}
              empty={{ title: t("nothingToPay"), hint: t("nothingToPayHint") }}
              columns={[
                { header: "", className: "w-10", cell: (b) => <Checkbox aria-label={t("select")} label="" checked={Number(amounts[b.id]) > 0} onChange={(e) => toggle(b, e.target.checked)} /> },
                { header: t("theirInvoice"), cell: (b) => <span className="font-medium">{b.supplier_invoice_no}</span> },
                { header: t("dueDate"), hideBelow: "sm", cell: (b) => <span className={isOverdue(b, day) ? "font-medium text-bad" : ""}>{formatDate(b.due_date)}</span> },
                { header: t("stillOwed"), align: "right", hideBelow: "md", cell: (b) => <Money value={b.due} companyId={b.company_id} /> },
                { header: t("payNow"), align: "right", className: "w-36", cell: (b) => <NumberInput aria-label={t("payNow")} value={amounts[b.id] ?? ""} onChange={(v) => setAmounts((a) => ({ ...a, [b.id]: v }))} /> },
                { header: t("result"), hideBelow: "sm", cell: (b) => (results[b.id] ? (results[b.id] === "ok" ? <Status status="paid" /> : <span className="text-xs text-bad">{results[b.id]}</span>) : "") },
              ]} />
          </Card>
        )}
      </div>
      <ConfirmDialog open={confirming} onClose={() => setConfirming(false)} busy={pay.isPending} onConfirm={() => pay.mutate()} title={t("confirmPayments")} confirmLabel={t("payTotal", { total: money(total, currency) })}
        message={t("confirmPaymentsMessage", { count: chosen.length, total: money(total, currency), supplier: supplier.data?.name ?? "" })} />
    </form>
  );
}
