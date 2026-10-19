import { Banknote, Gift, Undo2 } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, Card, DataTable, DetailList, Field, formatDate, Modal, money, NumberInput, Switch, toast, unwrap, useCan, useCurrency, useMutation, useQuery,
  useQueryClient, useTranslation,
} from "@/sdk";

import { owesMoney } from "../gymLogic";
import type { Member } from "../hooks";
import { sumDecimals } from "../logic";
import { RunsTable } from "./RunsTable";
import { CreditRunDialog, TakePaymentDialog } from "./PaymentDialogs";

type Due = { id: string; total: string | null; outstanding: string | null };

const STATE_TONE: Record<string, "ok" | "warn" | "bad" | "neutral"> = { paid: "ok", open: "warn", credited: "neutral", cancelled: "neutral" };

/** What is owed and paid, payments, write-offs and refunds, and the person's credit and points. */
export function MoneyTab({ member, customerId, companyId }: { member?: Member; customerId: string; companyId: string }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const currency = useCurrency(companyId);
  const canManage = useCan("memberships.manage");
  const canAdjust = useCan("memberships.credits");
  const [paying, setPaying] = useState(false);
  const [crediting, setCrediting] = useState<Due | null>(null);
  const [redeeming, setRedeeming] = useState(false);
  const [points, setPoints] = useState("");
  const dues = useQuery({
    enabled: !!member, queryKey: ["memberships", "dues", member?.id],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/members/{member_id}/dues", { params: { path: { member_id: member?.id ?? "" } } })),
  });
  const value = useQuery({ queryKey: ["memberships", "value", customerId], queryFn: () => unwrap(api.GET("/api/v1/memberships/customers/{customer_id}/value", { params: { path: { customer_id: customerId } } })) });
  const owed = sumDecimals((dues.data ?? []).filter((d) => d.status === "issued").map((d) => d.outstanding));
  const pause = useMutation({
    meta: { silent: true }, onError: (e) => toast((e as Error).message, "bad"),
    mutationFn: (v: { id: string; paused: boolean }) => unwrap(api.POST("/api/v1/memberships/invoice-runs/{run_id}/dunning", { params: { path: { run_id: v.id } }, body: { paused: v.paused } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["memberships", "dues"] }); toast(t("money.reminderSaved"), "ok"); },
  });
  const redeem = useMutation({
    meta: { silent: true }, onError: (e) => toast((e as Error).message, "bad"),
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/customers/{customer_id}/points/redeem", { params: { path: { customer_id: customerId } }, body: { points } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["memberships", "value"] }); toast(t("money.redeemed"), "ok"); setRedeeming(false); setPoints(""); },
  });

  return (
    <div className="space-y-4">
      {member && (
        <Card title={t("money.invoicesTitle")} description={owesMoney(owed) ? t("money.owedTotal", { amount: money(owed, currency) }) : t("money.nothingOwed")}
          actions={canManage && <Button onClick={() => setPaying(true)}><Banknote className="h-4 w-4" />{t("pay.take")}</Button>}>
          <DataTable rows={dues.data} loading={dues.isLoading} error={dues.error?.message} onRetry={() => void dues.refetch()} rowKey={(d) => d.id} dense
            empty={{ title: t("money.noInvoices"), hint: t("noInvoicesHint") }}
            columns={[
              { header: t("invoice"), cell: (d) => <span><span className="font-mono">{d.invoice_number ?? "—"}</span><span className="block text-xs text-muted">{formatDate(d.period_start)}</span></span> },
              { header: t("money.total"), hideBelow: "sm", align: "right", cell: (d) => (d.total ? money(d.total, currency) : "—") },
              { header: t("money.outstanding"), align: "right", cell: (d) => <span className={owesMoney(d.outstanding) ? "font-semibold text-bad" : ""}>{d.outstanding ? money(d.outstanding, currency) : "—"}</span> },
              { header: t("money.due"), hideBelow: "md", cell: (d) => (d.due_date ? formatDate(d.due_date) : "—") },
              { header: t("status"), cell: (d) => <Badge tone={STATE_TONE[d.settle_state] ?? "neutral"}>{t(`money.state.${d.settle_state}`, d.settle_state)}</Badge> },
              { header: "", align: "right", cell: (d) => d.status !== "issued" || d.settle_state !== "open" ? null : (
                <span className="flex flex-wrap justify-end gap-2">
                  {canManage && owesMoney(d.outstanding) && (
                    <Switch checked={!d.dunning_paused} onChange={(v) => pause.mutate({ id: d.id, paused: !v })} label={t("money.reminders")} />
                  )}
                  {canAdjust && <Button size="sm" variant="secondary" onClick={() => setCrediting({ id: d.id, total: d.total, outstanding: d.outstanding })}><Undo2 className="h-3.5 w-3.5" />{t("credit.button")}</Button>}
                </span>) },
            ]} />
        </Card>
      )}

      <Card title={t("money.valueTitle")} actions={canManage && Number(value.data?.points ?? 0) > 0 && <Button variant="secondary" onClick={() => setRedeeming(true)}><Gift className="h-4 w-4" />{t("money.redeem")}</Button>}>
        {value.error ? <p className="text-sm text-bad">{value.error.message} <button type="button" className="underline" onClick={() => void value.refetch()}>{t("retry")}</button></p>
          : !value.data ? <p className="text-sm text-muted">{t("loading")}</p>
          : <DetailList items={[
              { label: t("money.credit"), value: money(value.data.credit, currency) },
              { label: t("money.points"), value: value.data.points },
              { label: t("money.accounts"), value: value.data.accounts.length ? value.data.accounts.map((a) => `${t(`extras.kinds.${a.kind}`, a.kind)} ${money(a.balance, currency)}`).join(" · ") : "—" },
            ]} />}
      </Card>

      {member && <Card title={t("invoices")} flush><RunsTable ownerId={member.id} companyId={member.company_id} empty={{ title: t("noInvoices"), hint: t("noInvoicesHint") }} /></Card>}

      {member && <TakePaymentDialog open={paying} onClose={() => setPaying(false)} memberId={member.id} companyId={companyId} owed={owed} />}
      {crediting && <CreditRunDialog open onClose={() => setCrediting(null)} runId={crediting.id} companyId={companyId} outstanding={crediting.outstanding ?? "0"} total={crediting.total ?? "0"} />}
      <Modal open={redeeming} onClose={() => setRedeeming(false)} title={t("money.redeem")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setRedeeming(false)}>{t("cancel")}</Button><Button loading={redeem.isPending} disabled={!(Number(points) > 0)} onClick={() => redeem.mutate()}>{t("money.redeem")}</Button></>}>
        <Field label={t("money.pointsToUse")} hint={t("money.pointsHint", { points: value.data?.points ?? 0 })}><NumberInput value={points} onChange={setPoints} autoFocus /></Field>
      </Modal>
    </div>
  );
}
