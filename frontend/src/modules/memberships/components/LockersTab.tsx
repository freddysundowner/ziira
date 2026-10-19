import { Plus } from "lucide-react";
import { type ReactNode, useState } from "react";

import {
  api, Alert, Badge, Button, ConfirmDialog, cx, Drawer, EmptyState, ErrorState, Field, FormGrid, Input, Modal, money, NumberInput, Select, Skeleton, Textarea, toast, today, unwrap,
  useAccess, useCan, useCurrency, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { splitCodes } from "../gymLogic";
import { CustomerPicker, ServicePicker, useDeskBranch } from "../hooks";

type Locker = NonNullable<ReturnType<typeof useLockers>["data"]>[number];

function useLockers(companyId: string, branchId: string, status: string) {
  return useQuery({
    enabled: !!companyId, queryKey: ["memberships", "lockers", companyId, branchId, status],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/lockers", { params: { query: { company_id: companyId, branch_id: branchId || undefined, status: status || undefined } } })),
  });
}

const TONE = { free: "ok", assigned: "info", out_of_service: "neutral" } as const;

/** Lockers, towels and other things rented to members: a grid by status, add several at once, give to a customer, take back. */
export function LockersTab() {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const canManage = useCan("memberships.manage");
  const hasProducts = useAccess().enabledUnits.has("products");
  const { companyId, branchId, field } = useDeskBranch("");
  const currency = useCurrency(companyId);
  const [status, setStatus] = useState("");
  const [adding, setAdding] = useState(false);
  const [assigning, setAssigning] = useState<Locker | null>(null);
  const [releasing, setReleasing] = useState<Locker | null>(null);
  const [codes, setCodes] = useState("");
  const [kind, setKind] = useState<"locker" | "towel" | "other">("locker");
  const [fee, setFee] = useState("0");
  const [deposit, setDeposit] = useState("0");
  const [interval, setIntervalValue] = useState<"week" | "month" | "quarter" | "year">("month");
  const [product, setProduct] = useState("");
  const [customer, setCustomer] = useState("");
  const [start, setStart] = useState(today());
  const q = useLockers(companyId, branchId, status);
  const done = (message: string) => { void qc.invalidateQueries({ queryKey: ["memberships", "lockers"] }); toast(message, "ok"); };
  const fail = (e: unknown) => toast((e as Error).message, "bad");

  const add = useMutation({
    meta: { silent: true }, onError: fail,
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/lockers", { body: { company_id: companyId, branch_id: branchId, codes: splitCodes(codes), kind, fee: fee || "0", deposit: deposit || "0", billing_interval: interval, product_id: product || null } })),
    onSuccess: (rows) => { done(t("lockers.added", { count: rows.length })); setAdding(false); setCodes(""); },
  });
  const assign = useMutation({
    meta: { silent: true }, onError: fail,
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/lockers/{locker_id}/assign", { params: { path: { locker_id: assigning?.id ?? "" } }, body: { customer_id: customer, start_date: start || null } })),
    onSuccess: () => { done(t("lockers.assigned")); setAssigning(null); setCustomer(""); },
  });
  const release = useMutation({
    meta: { silent: true }, onError: fail,
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/lockers/{locker_id}/release", { params: { path: { locker_id: releasing?.id ?? "" } } })),
    onSuccess: () => { done(t("lockers.released")); setReleasing(null); },
  });
  const out = useMutation({
    meta: { silent: true }, onError: fail,
    mutationFn: (v: { id: string; out: boolean }) => unwrap(api.POST("/api/v1/memberships/lockers/{locker_id}/out-of-service", { params: { path: { locker_id: v.id }, query: { out: v.out } } })),
    onSuccess: () => done(t("lockers.updated")),
  });

  const counts = { free: 0, assigned: 0, out_of_service: 0 } as Record<string, number>;
  for (const l of q.data ?? []) counts[l.status] = (counts[l.status] ?? 0) + 1;
  const button = (l: Locker): ReactNode => (
    <button key={l.id} type="button" onClick={() => { if (l.status === "free" && canManage) setAssigning(l); else if (l.status === "assigned" && canManage) setReleasing(l); }}
      className={cx("min-h-20 rounded-xl border p-3 text-left", l.status === "free" ? "border-ok/40 bg-ok-soft" : l.status === "assigned" ? "border-info/40 bg-info-soft" : "border-line bg-sunken")}>
      <span className="flex items-center justify-between gap-2"><span className="font-mono text-lg font-bold">{l.code}</span><Badge tone={TONE[l.status as keyof typeof TONE] ?? "neutral"}>{t(`lockers.status.${l.status}`, l.status)}</Badge></span>
      <span className="mt-1 block truncate text-sm">{l.customer_name ?? (Number(l.fee) > 0 ? `${money(l.fee, currency)} / ${t(`unit.${l.billing_interval}`)}` : t(`lockers.kinds.${l.kind}`, l.kind))}</span>
    </button>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        {field}
        <Select className="w-44" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t("allStatuses")}</option>
          {(["free", "assigned", "out_of_service"] as const).map((x) => <option key={x} value={x}>{t(`lockers.status.${x}`)}</option>)}
        </Select>
        <span className="text-sm text-muted">{t("lockers.summary", { free: counts.free, assigned: counts.assigned })}</span>
        {canManage && <Button className="ml-auto" onClick={() => setAdding(true)}><Plus className="h-4 w-4" />{t("lockers.add")}</Button>}
      </div>
      {q.error ? <ErrorState message={q.error.message} onRetry={() => void q.refetch()} />
        : q.isLoading ? <div className="grid grid-cols-2 gap-3 md:grid-cols-4"><Skeleton className="h-20" /><Skeleton className="h-20" /><Skeleton className="h-20" /><Skeleton className="h-20" /></div>
        : q.data && q.data.length === 0 ? <EmptyState title={t("lockers.empty")} hint={t("lockers.emptyHint")} action={canManage ? <Button onClick={() => setAdding(true)}>{t("lockers.add")}</Button> : undefined} />
        : <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">{q.data?.map(button)}</div>}
      {canManage && q.data && q.data.some((l) => l.status !== "assigned") && <p className="text-xs text-muted">{t("lockers.tapHint")}</p>}

      <Drawer open={adding} onClose={() => setAdding(false)} title={t("lockers.add")}
        footer={<><Button variant="secondary" onClick={() => setAdding(false)}>{t("cancel")}</Button><Button loading={add.isPending} disabled={splitCodes(codes).length === 0} onClick={() => add.mutate()}>{t("lockers.add")}</Button></>}>
        <div className="space-y-4">
          <Field label={t("lockers.codes")} hint={t("lockers.codesHint")} required><Textarea rows={3} value={codes} autoFocus onChange={(e) => setCodes(e.target.value)} placeholder="L1, L2, L3" /></Field>
          <p className="text-xs text-muted">{t("lockers.codesCount", { count: splitCodes(codes).length })}</p>
          <FormGrid>
            <Field label={t("lockers.kind")}><Select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>{(["locker", "towel", "other"] as const).map((x) => <option key={x} value={x}>{t(`lockers.kinds.${x}`)}</option>)}</Select></Field>
            <Field label={t("lockers.every")}><Select value={interval} onChange={(e) => setIntervalValue(e.target.value as typeof interval)}>{(["week", "month", "quarter", "year"] as const).map((x) => <option key={x} value={x}>{t(`unit.${x}`)}</option>)}</Select></Field>
          </FormGrid>
          <FormGrid>
            <Field label={t("lockers.fee")}><NumberInput value={fee} onChange={setFee} /></Field>
            <Field label={t("lockers.deposit")} hint={t("lockers.depositHint")}><NumberInput value={deposit} onChange={setDeposit} /></Field>
          </FormGrid>
          {hasProducts && <ServicePicker value={product} onChange={setProduct} label={t("invoicedAs")} hint={t("invoicedAsHint")} clearable />}
        </div>
      </Drawer>

      <Modal open={!!assigning} onClose={() => setAssigning(null)} title={t("lockers.giveTitle", { code: assigning?.code ?? "" })} size="sm"
        footer={<><Button variant="secondary" onClick={() => setAssigning(null)}>{t("cancel")}</Button><Button loading={assign.isPending} disabled={!customer} onClick={() => assign.mutate()}>{t("lockers.give")}</Button></>}>
        <div className="space-y-4">
          {assigning && (Number(assigning.fee) > 0 || Number(assigning.deposit) > 0) && (
            <Alert tone="info">{t("lockers.costs", { fee: money(assigning.fee, currency), deposit: money(assigning.deposit, currency) })}</Alert>
          )}
          <CustomerPicker value={customer} onChange={setCustomer} required />
          <Field label={t("startDate")}><Input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        </div>
      </Modal>
      <ConfirmDialog open={!!releasing} onClose={() => setReleasing(null)} title={t("lockers.takeBackTitle", { code: releasing?.code ?? "" })}
        message={t("lockers.takeBackMessage", { name: releasing?.customer_name ?? "" })} confirmLabel={t("lockers.takeBack")} busy={release.isPending} onConfirm={() => release.mutate()} />
      {canManage && q.data?.filter((l) => l.status !== "assigned").length ? (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted">{t("lockers.outOfService")}</summary>
          <ul className="mt-2 flex flex-wrap gap-2">
            {q.data.filter((l) => l.status !== "assigned").map((l) => (
              <li key={l.id}><Button size="sm" variant="secondary" loading={out.isPending} onClick={() => out.mutate({ id: l.id, out: l.status !== "out_of_service" })}>{l.code}: {l.status === "out_of_service" ? t("lockers.putBack") : t("lockers.putOut")}</Button></li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
