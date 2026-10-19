import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { api, Button, Card, ErrorText, Field, IconButton, Input, money, NumberInput, Select, Switch, toast, unwrap, useQuery, useTranslation } from "@/sdk";

import type { Resource } from "../types";
import { newKey } from "./logic";

export const PAY_METHODS = ["cash", "mobile_money", "card", "bank", "other"] as const;
export const TIP_METHODS = ["cash", "mobile_money", "card", "other"] as const;

export interface PayRow { key: string; method: (typeof PAY_METHODS)[number]; amount: string; reference: string }
export interface TenderRow { key: string; kind: string; code: string; amount: string }
export interface TipRow { key: string; resource_id: string; amount: string; method: (typeof TIP_METHODS)[number] }

export const payRow = (method: PayRow["method"], amount = ""): PayRow => ({ key: newKey(), method, amount, reference: "" });

/** Tips for the staff on the bill. Used before payment (with the bill) and after it (a tip added later). */
export function TipsEditor({ tips, onChange, staff, defaults }: { tips: TipRow[]; onChange: (rows: TipRow[]) => void; staff: readonly Resource[]; defaults: string[] }) {
  const { t } = useTranslation("bookings");
  const patch = (key: string, change: Partial<TipRow>) => onChange(tips.map((r) => (r.key === key ? { ...r, ...change } : r)));
  return (
    <div className="space-y-3">
      {tips.map((r) => (
        <div key={r.key} className="grid grid-cols-[1fr_auto] items-end gap-2 sm:grid-cols-[1fr_8rem_9rem_auto]">
          <Field label={t("checkout.tipFor")} className="col-span-2 sm:col-span-1">
            <Select value={r.resource_id} onChange={(e) => patch(r.key, { resource_id: e.target.value })}>
              {staff.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </Field>
          <Field label={t("checkout.amount")}><NumberInput value={r.amount} onChange={(v) => patch(r.key, { amount: v })} /></Field>
          <Field label={t("checkout.method")}>
            <Select value={r.method} onChange={(e) => patch(r.key, { method: e.target.value as TipRow["method"] })}>
              {TIP_METHODS.map((m) => <option key={m} value={m}>{t(`checkout.methods.${m}`)}</option>)}
            </Select>
          </Field>
          <IconButton label={t("checkout.removeRow")} onClick={() => onChange(tips.filter((x) => x.key !== r.key))}><Trash2 className="h-4 w-4" /></IconButton>
        </div>
      ))}
      <Button variant="secondary" disabled={staff.length === 0}
        onClick={() => onChange([...tips, { key: newKey(), resource_id: defaults[tips.length % Math.max(defaults.length, 1)] ?? staff[0]?.id ?? "", amount: "", method: "cash" }])}>
        <Plus className="h-4 w-4" />{t("checkout.addTip")}
      </Button>
    </div>
  );
}

/** How the client pays: split payments, other ways to pay (voucher, points) and the deposit already held. */
export function PaymentsPanel({ total, currency, customerId, payments, onPayments, tenders, onTenders, depositHeld, useDeposit, onUseDeposit }: {
  total: string; currency?: string; customerId: string | null; payments: PayRow[]; onPayments: (rows: PayRow[]) => void;
  tenders: TenderRow[]; onTenders: (rows: TenderRow[]) => void; depositHeld: string; useDeposit: boolean; onUseDeposit: (v: boolean) => void;
}) {
  const { t } = useTranslation("bookings");
  const kinds = useQuery({ queryKey: ["bookings", "tender-kinds"], staleTime: 5 * 60_000, queryFn: () => unwrap(api.GET("/api/v1/bookings/checkout/tenders")) });
  const [balances, setBalances] = useState<Record<string, string>>({});
  const [checking, setChecking] = useState<string | null>(null);
  const patchPay = (key: string, change: Partial<PayRow>) => onPayments(payments.map((r) => (r.key === key ? { ...r, ...change } : r)));
  const patchTender = (key: string, change: Partial<TenderRow>) => onTenders(tenders.map((r) => (r.key === key ? { ...r, ...change } : r)));
  const kindList = kinds.data ?? [];

  const checkBalance = async (row: TenderRow) => {
    setChecking(row.key);
    try {
      const b = await unwrap(api.GET("/api/v1/bookings/checkout/tenders/{kind}/balance", { params: { path: { kind: row.kind }, query: { customer_id: customerId ?? undefined, code: row.code.trim() || undefined } } }));
      setBalances((x) => ({ ...x, [row.key]: t("checkout.balanceIs", { amount: money(b.available, currency), what: b.description }) }));
    } catch (e) {
      toast(e instanceof Error ? e.message : t("checkout.balanceFailed"), "bad");
    } finally {
      setChecking(null);
    }
  };

  return (
    <Card title={t("checkout.paymentsTitle")}>
      <div className="space-y-4">
        <div className="flex flex-wrap gap-2">
          <Button size="lg" onClick={() => onPayments([payRow("cash", total)])}>{t("checkout.payAllCash")}</Button>
          <Button size="lg" variant="secondary" onClick={() => onPayments([payRow("card", total)])}>{t("checkout.payAllCard")}</Button>
        </div>
        {Number(depositHeld) > 0 && (
          <label className="flex items-center gap-3 rounded-lg bg-info-soft p-3 text-sm text-info">
            <Switch checked={useDeposit} onChange={onUseDeposit} label={t("checkout.useDeposit", { amount: money(depositHeld, currency) })} />
            <span>{t("checkout.useDeposit", { amount: money(depositHeld, currency) })}</span>
          </label>
        )}
        {payments.map((r) => (
          <div key={r.key} className="grid grid-cols-2 items-end gap-2 sm:grid-cols-[9rem_8rem_1fr_auto]">
            <Field label={t("checkout.method")}>
              <Select value={r.method} onChange={(e) => patchPay(r.key, { method: e.target.value as PayRow["method"] })}>
                {PAY_METHODS.map((m) => <option key={m} value={m}>{t(`checkout.methods.${m}`)}</option>)}
              </Select>
            </Field>
            <Field label={t("checkout.amount")}><NumberInput value={r.amount} onChange={(v) => patchPay(r.key, { amount: v })} /></Field>
            <Field label={t("checkout.reference")} className="col-span-2 sm:col-span-1"><Input value={r.reference} maxLength={80} onChange={(e) => patchPay(r.key, { reference: e.target.value })} /></Field>
            <IconButton label={t("checkout.removeRow")} className="justify-self-end" onClick={() => onPayments(payments.filter((x) => x.key !== r.key))}><Trash2 className="h-4 w-4" /></IconButton>
          </div>
        ))}
        <Button variant="secondary" onClick={() => onPayments([...payments, payRow("cash")])}><Plus className="h-4 w-4" />{t("checkout.addPayment")}</Button>

        {kinds.error && <ErrorText>{kinds.error.message}</ErrorText>}
        {kindList.length > 0 && (
          <div className="space-y-3 border-t border-line pt-4">
            <h3 className="text-[13px] font-semibold">{t("checkout.otherWays")}</h3>
            {tenders.map((r) => {
              const kind = kindList.find((k) => k.kind === r.kind);
              return (
                <div key={r.key} className="space-y-1">
                  <div className="grid grid-cols-2 items-end gap-2 sm:grid-cols-[10rem_1fr_8rem_auto_auto]">
                    <Field label={t("checkout.tenderKind")}>
                      <Select value={r.kind} onChange={(e) => patchTender(r.key, { kind: e.target.value })}>
                        {kindList.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
                      </Select>
                    </Field>
                    <Field label={t("checkout.tenderCode")} className="col-span-2 sm:col-span-1">
                      <Input value={r.code} maxLength={80} disabled={kind ? !kind.needs_code : false} onChange={(e) => patchTender(r.key, { code: e.target.value })} />
                    </Field>
                    <Field label={t("checkout.amount")}><NumberInput value={r.amount} onChange={(v) => patchTender(r.key, { amount: v })} /></Field>
                    <Button variant="secondary" loading={checking === r.key} onClick={() => void checkBalance(r)}>{t("checkout.checkBalance")}</Button>
                    <IconButton label={t("checkout.removeRow")} onClick={() => onTenders(tenders.filter((x) => x.key !== r.key))}><Trash2 className="h-4 w-4" /></IconButton>
                  </div>
                  {balances[r.key] && <p className="text-xs text-muted" role="status">{balances[r.key]}</p>}
                </div>
              );
            })}
            <Button variant="secondary" onClick={() => onTenders([...tenders, { key: newKey(), kind: kindList[0]?.kind ?? "", code: "", amount: "" }])}><Plus className="h-4 w-4" />{t("checkout.addOtherWay")}</Button>
          </div>
        )}
      </div>
    </Card>
  );
}
