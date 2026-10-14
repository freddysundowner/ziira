import { Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  Alert, api, Button, Drawer, Field, FormGrid, formatDate, IconButton, Input, money, NumberInput, quantity, Select, toast, today, unwrap, useCurrency, useMutation,
  useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { useExpenseAccounts } from "../hooks";
import { isPositive, previewSubtotal, remaining } from "../lib";
import type { BillSummary } from "../types";
import { useLines } from "./lines";
import { ProductName } from "./names";

interface Line { key: string; return_line_id: string; product_id: string; expense_account_id: string; description: string; quantity: string; unit_cost: string }

/** Record the credit note a supplier gave against a posted bill: for goods sent back, or any other allowance. Mount only while open. */
export function CreditNoteDrawer({ bill, onClose }: { bill: BillSummary; onClose: () => void }) {
  const { t } = useTranslation("purchasing");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const currency = useCurrency(bill.company_id);
  const [creditNo, setCreditNo] = useState("");
  const [date, setDate] = useState(today());
  const [returnId, setReturnId] = useState("");
  const { lines, add, update, remove } = useLines<Line>(() => ({ return_line_id: "", product_id: "", expense_account_id: "", description: "", quantity: "1", unit_cost: "" }));
  const accounts = useExpenseAccounts(bill.company_id);
  const returns = useQuery({ queryKey: ["purchasing", "returns", { supplier: bill.supplier_id }], queryFn: () => unwrap(api.GET("/api/v1/purchasing/returns", { params: { query: { supplier_id: bill.supplier_id, limit: 100 } } })) });
  const returnId2 = returnId || returns.data?.[0]?.id || "";
  const chosen = useQuery({ enabled: !!returnId2, queryKey: ["purchasing", "return", returnId2], queryFn: () => unwrap(api.GET("/api/v1/purchasing/returns/{return_id}", { params: { path: { return_id: returnId2 } } })) });
  const open = (chosen.data?.lines ?? []).filter((l) => Number(remaining(l.quantity, l.qty_credited)) > 0 && !lines.some((x) => x.return_line_id === l.id));

  const valid = !!creditNo.trim() && lines.length > 0 && lines.every((l) => isPositive(l.quantity) && l.unit_cost !== "" && (l.return_line_id || l.description.trim() || l.expense_account_id));
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/purchasing/bills/{bill_id}/credit-notes", { params: { path: { bill_id: bill.id } }, body: {
      supplier_credit_no: creditNo.trim(), credit_date: date, lines: lines.map((l) => ({
        quantity: l.quantity, unit_cost: l.unit_cost, return_line_id: l.return_line_id || null, expense_account_id: l.expense_account_id || null, description: l.description.trim() || null })) } })),
    onSuccess: (c) => { void qc.invalidateQueries({ queryKey: ["purchasing"] }); toast(t("creditSaved", { number: c.number }), "ok"); onClose(); navigate(`/credit-notes/${c.id}`); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Drawer open onClose={onClose} title={t("recordCredit", { number: bill.number })}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="credit-form" loading={save.isPending} disabled={!valid}>{t("save")}</Button></>}>
      <form id="credit-form" onSubmit={submit} className="space-y-4">
        <FormGrid>
          <Field label={t("theirCreditNo")} required><Input value={creditNo} maxLength={60} autoFocus onChange={(e) => setCreditNo(e.target.value)} /></Field>
          <Field label={t("date")}><Input type="date" max={today()} value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        </FormGrid>
        <div className="space-y-2 rounded-lg border border-line p-3">
          <p className="text-sm font-medium">{t("creditForGoods")}</p>
          {returns.data?.length === 0 && <p className="text-xs text-muted">{t("noSupplierReturns")}</p>}
          {(returns.data?.length ?? 0) > 0 && (
            <Select aria-label={t("returnRef")} value={returnId2} onChange={(e) => setReturnId(e.target.value)}>
              {returns.data?.map((r) => <option key={r.id} value={r.id}>{r.number} · {formatDate(r.returned_at)}</option>)}
            </Select>
          )}
          {open.map((l) => (
            <div key={l.id} className="flex items-center justify-between gap-2 text-sm">
              <span className="min-w-0"><ProductName id={l.product_id} /> <span className="text-muted">× {quantity(remaining(l.quantity, l.qty_credited))}</span></span>
              <Button size="sm" variant="secondary" onClick={() => add({ return_line_id: l.id, product_id: l.product_id, quantity: remaining(l.quantity, l.qty_credited), unit_cost: l.unit_cost })}>{t("add")}</Button>
            </div>
          ))}
          <Button size="sm" variant="ghost" onClick={() => add()}>{t("addAllowance")}</Button>
        </div>
        {lines.length === 0 && <Alert tone="info">{t("creditLinesHint")}</Alert>}
        <div className="space-y-2">
          {lines.map((l) => (
            <div key={l.key} className="space-y-2 rounded-lg border border-line bg-sunken/40 p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="text-sm">{l.return_line_id ? <ProductName id={l.product_id} /> : <span className="font-medium">{t("otherAllowance")}</span>}</div>
                <IconButton label={t("removeLine")} onClick={() => remove(l.key)}><Trash2 className="h-4 w-4" /></IconButton>
              </div>
              {!l.return_line_id && (
                <FormGrid>
                  <Field label={t("description")}><Input value={l.description} maxLength={200} onChange={(e) => update(l.key, { description: e.target.value })} /></Field>
                  {(accounts.data?.length ?? 0) > 0 && (
                    <Field label={t("expenseAccount")}>
                      <Select value={l.expense_account_id} onChange={(e) => update(l.key, { expense_account_id: e.target.value })}>
                        <option value="">{t("choose")}</option>{accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}
                      </Select>
                    </Field>
                  )}
                </FormGrid>
              )}
              <FormGrid>
                <Field label={t("quantity")}><NumberInput value={l.quantity} onChange={(v) => update(l.key, { quantity: v })} /></Field>
                <Field label={t("unitCostBeforeTax")}><NumberInput value={l.unit_cost} onChange={(v) => update(l.key, { unit_cost: v })} /></Field>
              </FormGrid>
            </div>
          ))}
        </div>
        <p className="text-right text-sm text-muted">{t("previewSubtotal")}: <span className="tnum font-medium text-ink">{money(previewSubtotal(lines), currency)}</span></p>
      </form>
    </Drawer>
  );
}
