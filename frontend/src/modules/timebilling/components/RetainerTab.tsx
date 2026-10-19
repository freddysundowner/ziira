import { type FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  Alert, api, Badge, Button, Card, DataTable, DetailList, Field, formatDate, FormGrid, Input, Modal, money, NumberInput, percent, Select, Skeleton, ErrorState, EmptyState, Switch, Textarea, toast, today, unwrap, useCan, useCompany,
  useFormState, useMutation, useQuery, useTranslation,
} from "@/sdk";

import { useRefresh } from "../hooks";
import { barWidth, formatDuration, LONG_MINUTES, parseDuration } from "../lib";
import type { Project, Retainer, RetainerTxn } from "../types";

/** The prepaid hours or monthly fee of a retainer project: balance, history, and billing a top-up or a month. */
export function RetainerTab({ project, currency }: { project: Project; currency?: string }) {
  const { t } = useTranslation("timebilling");
  const canManage = useCan("projects.manage");
  const canBill = useCan("time.bill");
  const [dialog, setDialog] = useState<"create" | "edit" | "topup" | "fee" | null>(null);
  const list = useQuery({
    queryKey: ["timebilling", "retainers", project.id],
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/retainers", { params: { query: { project_id: project.id } } })),
  });
  if (list.isLoading) return <Skeleton className="h-40 w-full" />;
  if (list.error) return <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />;
  const retainer = list.data?.find((r) => r.status === "active") ?? list.data?.[0];

  if (!retainer) {
    return (
      <>
        <EmptyState title={t("retainer.empty")} hint={t("retainer.emptyHint")} action={canManage ? <Button onClick={() => setDialog("create")}>{t("retainer.create")}</Button> : undefined} />
        <RetainerForm project={project} open={dialog === "create"} onClose={() => setDialog(null)} />
      </>
    );
  }
  const closed = retainer.status !== "active";
  const near = retainer.used_percent >= retainer.alert_percent;
  return (
    <div className="space-y-4">
      {near && !closed && <Alert tone={retainer.used_percent >= 100 ? "bad" : "warn"}>{t(retainer.used_percent >= 100 ? "retainer.usedUp" : "retainer.nearlyUsed", { percent: retainer.used_percent })}</Alert>}
      <Card title={t(retainer.kind === "hours" ? "retainer.kindHours" : "retainer.kindFee")} actions={
        <>
          {canBill && !closed && retainer.kind === "hours" && <Button size="sm" onClick={() => setDialog("topup")}>{t("retainer.billTopup")}</Button>}
          {canBill && !closed && retainer.kind === "monthly_fee" && <Button size="sm" onClick={() => setDialog("fee")}>{t("retainer.billMonth")}</Button>}
          {canManage && <Button size="sm" variant="secondary" onClick={() => setDialog("edit")}>{t("edit")}</Button>}
        </>}>
        <div className="space-y-4">
          <div>
            <div className="mb-1 flex items-baseline justify-between text-sm">
              <span className="font-medium">{t("retainer.balance")}: <span className="tnum">{formatDuration(retainer.balance_minutes)}</span></span>
              <span className="tnum text-muted">{t("retainer.usedOf", { percent: retainer.used_percent, total: formatDuration(retainer.topped_up_minutes) })}</span>
            </div>
            <div className="h-2.5 overflow-hidden rounded-full bg-sunken" role="img" aria-label={`${t("retainer.used")}: ${percent(retainer.used_percent, 0)}`}>
              <div className={`h-full rounded-full ${retainer.used_percent >= 100 ? "bg-bad" : near ? "bg-warn" : "bg-brand"}`} style={{ width: `${barWidth(retainer.used_percent)}%` }} />
            </div>
          </div>
          <DetailList items={[
            { label: t("status"), value: <Badge tone={closed ? "neutral" : "ok"}>{t(`retainer.status.${retainer.status}`, retainer.status)}</Badge> },
            ...(retainer.monthly_fee ? [{ label: t("retainer.monthlyFee"), value: money(retainer.monthly_fee, currency) }] : []),
            { label: t("retainer.expires"), value: retainer.expires_on ? formatDate(retainer.expires_on) : t("retainer.noExpiry") },
            { label: t("retainer.alertAt"), value: `${retainer.alert_percent}%` },
            { label: t("note"), value: retainer.note || "—" },
          ]} />
        </div>
      </Card>
      <History retainer={retainer} currency={currency} />
      <RetainerForm project={project} retainer={retainer} open={dialog === "edit"} onClose={() => setDialog(null)} />
      <BillDialog retainer={retainer} project={project} kind="topup" open={dialog === "topup"} onClose={() => setDialog(null)} currency={currency} />
      <BillDialog retainer={retainer} project={project} kind="fee" open={dialog === "fee"} onClose={() => setDialog(null)} currency={currency} />
    </div>
  );
}

function History({ retainer, currency }: { retainer: Retainer; currency?: string }) {
  const { t } = useTranslation("timebilling");
  const history = useQuery<RetainerTxn[]>({
    queryKey: ["timebilling", "retainer-history", retainer.id],
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/retainers/{retainer_id}/history", { params: { path: { retainer_id: retainer.id } } })),
  });
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold">{t("retainer.history")}</h3>
      <DataTable rows={history.data} loading={history.isLoading} error={history.error?.message} onRetry={() => void history.refetch()} rowKey={(x) => x.id}
        empty={{ title: t("retainer.noHistory") }}
        columns={[
          { header: t("date"), cell: (x) => formatDate(x.occurred_on) },
          { header: t("retainer.what"), cell: (x) => <span className="font-medium">{t(`retainer.txn.${x.kind}`, x.kind)}</span> },
          { header: t("time"), align: "right", cell: (x) => <span className={`tnum ${x.minutes < 0 ? "text-bad" : ""}`}>{x.minutes < 0 ? "−" : ""}{formatDuration(Math.abs(x.minutes))}</span> },
          { header: t("expenses.amount"), align: "right", hideBelow: "sm", cell: (x) => (x.amount ? <span className="tnum">{money(x.amount, currency)}</span> : "—") },
          { header: t("note"), hideBelow: "md", cell: (x) => x.note ?? "—" },
        ]} />
    </section>
  );
}

function RetainerForm({ project, retainer, open, onClose }: { project: Project; retainer?: Retainer; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const f = useFormState({ kind: "hours", fee: "", expires: "", alert: "80", opening: "", note: "", status: "active", billDay: "1" });
  const [autoDraft, setAutoDraft] = useState(true);
  const { reset, set } = f;
  useEffect(() => {
    if (!open) return;
    reset();
    if (retainer) { set("kind", retainer.kind); set("fee", retainer.monthly_fee ?? ""); set("expires", retainer.expires_on ?? ""); set("alert", String(retainer.alert_percent)); set("note", retainer.note ?? ""); set("status", retainer.status); set("billDay", String(retainer.bill_day)); setAutoDraft(retainer.auto_draft); }
    else setAutoDraft(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, retainer?.id]);
  const opening = parseDuration(f.values.opening, LONG_MINUTES);
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const v = f.values;
      if (retainer) {
        return unwrap(api.PATCH("/api/v1/timebilling/retainers/{retainer_id}", { params: { path: { retainer_id: retainer.id } }, body: {
          expires_on: v.expires || null, alert_percent: Number(v.alert) || 80, monthly_fee: v.kind === "monthly_fee" ? v.fee || null : null, note: v.note.trim() || null, status: v.status as "active", bill_day: Number(v.billDay) || 1, auto_draft: autoDraft } }));
      }
      return unwrap(api.POST("/api/v1/timebilling/projects/{project_id}/retainer", { params: { path: { project_id: project.id } }, body: {
        kind: v.kind as "hours", monthly_fee: v.kind === "monthly_fee" ? v.fee || null : null, expires_on: v.expires || null, alert_percent: Number(v.alert) || 80, opening_minutes: opening ?? 0, note: v.note.trim() || null, bill_day: Number(v.billDay) || 1, auto_draft: autoDraft } }));
    },
    onSuccess: () => { void refresh(); toast(t("retainer.saved"), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Modal open={open} onClose={onClose} title={t(retainer ? "retainer.edit" : "retainer.create")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="retainer-form" loading={save.isPending} disabled={f.values.opening !== "" && opening === null}>{t("save")}</Button></>}>
      <form id="retainer-form" onSubmit={submit} className="space-y-4">
        <Field label={t("retainer.kind")} hint={t(f.values.kind === "hours" ? "retainer.kindHoursHint" : "retainer.kindFeeHint")} error={f.error("kind")}>
          <Select {...f.bind("kind")} disabled={!!retainer}><option value="hours">{t("retainer.kindHours")}</option><option value="monthly_fee">{t("retainer.kindFee")}</option></Select>
        </Field>
        {f.values.kind === "monthly_fee" && <Field label={t("retainer.monthlyFee")} required error={f.error("monthly_fee")}><NumberInput value={f.values.fee} onChange={(v) => f.set("fee", v)} required /></Field>}
        <FormGrid>
          <Field label={t("retainer.expires")} hint={t("retainer.expiresHint")} error={f.error("expires_on")}><Input type="date" {...f.bind("expires")} min={today()} /></Field>
          <Field label={t("retainer.alertAt")} hint={t("retainer.alertHint")} error={f.error("alert_percent")}><NumberInput value={f.values.alert} onChange={(v) => f.set("alert", v)} /></Field>
        </FormGrid>
        {f.values.kind === "monthly_fee" && (
          <>
            <Field label={t("retainer.billDay")} hint={t("retainer.billDayHint")} error={f.error("bill_day")}><NumberInput value={f.values.billDay} onChange={(v) => f.set("billDay", v.replace(/\./g, ""))} /></Field>
            <div className="flex items-start justify-between gap-4"><div><p className="text-sm font-medium">{t("retainer.autoDraft")}</p><p className="text-xs text-muted">{t("retainer.autoDraftHint")}</p></div><Switch checked={autoDraft} onChange={setAutoDraft} label={t("retainer.autoDraft")} /></div>
          </>
        )}
        {!retainer && <Field label={t("retainer.opening")} hint={t("retainer.openingHint")} error={f.error("opening_minutes") ?? (f.values.opening !== "" && opening === null ? t("timeInvalid") : null)}><Input {...f.bind("opening")} placeholder="10:00" /></Field>}
        {retainer && (
          <Field label={t("status")} error={f.error("status")}>
            <Select {...f.bind("status")}><option value="active">{t("retainer.status.active")}</option><option value="closed">{t("retainer.status.closed")}</option></Select>
          </Field>
        )}
        <Field label={t("note")} error={f.error("note")}><Textarea {...f.bind("note")} maxLength={500} /></Field>
      </form>
    </Modal>
  );
}

/** "Bill a top-up" (hours and the price) or "Bill a month": starts an invoice review and opens it. */
function BillDialog({ retainer, project, kind, open, onClose, currency }: { retainer: Retainer; project: Project; kind: "topup" | "fee"; open: boolean; onClose: () => void; currency?: string }) {
  const { t } = useTranslation("timebilling");
  const navigate = useNavigate();
  const refresh = useRefresh();
  const branches = useCompany(project.company_id).company?.branches ?? [];
  const needsBranch = !project.branch_id && branches.length > 1;
  const [branch, setBranch] = useState("");
  const f = useFormState({ hours: "", amount: "", month: today().slice(0, 7), memo: "" });
  const { reset } = f;
  useEffect(() => { if (open) { reset(); setBranch(branches[0]?.id ?? ""); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  const minutes = parseDuration(f.values.hours, LONG_MINUTES);
  const start = useMutation({
    meta: { silent: true },
    mutationFn: () => kind === "topup"
      ? unwrap(api.POST("/api/v1/timebilling/retainers/{retainer_id}/topup", { params: { path: { retainer_id: retainer.id } }, body: { minutes: minutes ?? 0, amount: f.values.amount, memo: f.values.memo.trim() || null, branch_id: needsBranch ? branch : null } }))
      : unwrap(api.POST("/api/v1/timebilling/retainers/{retainer_id}/fee", { params: { path: { retainer_id: retainer.id } }, body: { period: f.values.month, branch_id: needsBranch ? branch : null } })),
    onSuccess: (review) => { void refresh(); onClose(); navigate(`/time/reviews/${review.id}`); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); start.mutate(); };
  const ready = kind === "topup" ? !!minutes && Number(f.values.amount) > 0 : /^\d{4}-\d{2}$/.test(f.values.month);
  return (
    <Modal open={open} onClose={onClose} title={t(kind === "topup" ? "retainer.billTopup" : "retainer.billMonth")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="bill-retainer" loading={start.isPending} disabled={!ready}>{t("retainer.startReview")}</Button></>}>
      <form id="bill-retainer" onSubmit={submit} className="space-y-4">
        {needsBranch && <Field label={t("branch")} hint={t("review.branchHint")}><Select value={branch} onChange={(e) => setBranch(e.target.value)}>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select></Field>}
        <p className="text-sm text-muted">{t(kind === "topup" ? "retainer.topupHint" : "retainer.feeHint", { fee: money(retainer.monthly_fee, currency) })}</p>
        {kind === "topup" ? (
          <>
            <FormGrid>
              <Field label={t("retainer.hoursToAdd")} required error={f.error("minutes") ?? (f.values.hours !== "" && minutes === null ? t("timeInvalid") : null)}><Input {...f.bind("hours")} placeholder="10:00" /></Field>
              <Field label={t("retainer.price")} required error={f.error("amount")}><NumberInput value={f.values.amount} onChange={(v) => f.set("amount", v)} /></Field>
            </FormGrid>
            <Field label={t("retainer.memo")} error={f.error("memo")}><Input {...f.bind("memo")} maxLength={500} /></Field>
          </>
        ) : (
          <Field label={t("retainer.month")} required error={f.error("period")}><Input type="month" {...f.bind("month")} required /></Field>
        )}
      </form>
    </Modal>
  );
}
