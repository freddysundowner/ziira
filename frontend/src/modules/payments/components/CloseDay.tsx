import { useEffect, useState } from "react";

import {
  api, Alert, Button, ConfirmDialog, Drawer, Field, formatDate, FormGrid, humanise, Input, money, NumberInput, Select, Skeleton, Textarea, today, toast, unwrap,
  useCompany, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { flattenTotals, looksNumeric } from "../logic";

/** Close a branch's day: see the takings and what stops it closing, enter the cash banked, explain any variance, lock it. */
export function CloseDay({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation("payments");
  const qc = useQueryClient();
  const { company } = useCompany();
  const branches = company?.branches ?? [];
  const [branchId, setBranchId] = useState("");
  const [date, setDate] = useState(today());
  const [banked, setBanked] = useState("");
  const [why, setWhy] = useState("");
  const [confirming, setConfirming] = useState(false);
  const branch = branchId || branches[0]?.id || "";
  useEffect(() => { if (open) { setBanked(""); setWhy(""); setDate(today()); } }, [open]);

  const preview = useQuery({
    enabled: open && !!company && !!branch && !!date, queryKey: ["close-preview", company?.id, branch, date, banked],
    queryFn: () => unwrap(api.GET("/api/v1/payments/closes/preview", { params: { query: { company_id: company?.id ?? "", branch_id: branch, business_date: date, cash_banked: banked || undefined } } })),
  });
  const submit = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/payments/closes", { body: { company_id: company?.id ?? "", branch_id: branch, business_date: date, cash_banked: banked, explanation: why.trim() || null } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["closes"] }); toast(t("dayClosed", { date: formatDate(date) }), "ok"); setConfirming(false); onClose(); },
    onError: (e) => { setConfirming(false); toast((e as Error).message, "bad"); },
  });

  const p = preview.data;
  const lines = p ? flattenTotals(p.totals) : [];
  const already = p && (p.close.status === "submitted" || p.close.status === "locked");
  const variance = p?.totals.variance;
  const hasVariance = typeof variance === "string" && Number(variance) !== 0;
  const label = (path: string[]) => path.map((k) => t(`totalsLabels.${k}`, humanise(k))).join(" · ");

  return (
    <Drawer open={open} onClose={onClose} title={t("closeDay")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button disabled={!banked || !!already || !p || preview.isFetching} onClick={() => setConfirming(true)}>{t("closeAndLock")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("closeHint")}</p>
        <FormGrid>
          {branches.length > 1 && (
            <Field label={t("branch")}><Select value={branch} onChange={(e) => setBranchId(e.target.value)}>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select></Field>
          )}
          <Field label={t("day")}><Input type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} /></Field>
        </FormGrid>
        <Field label={t("cashBanked")} required hint={t("cashBankedHint")}><NumberInput value={banked} onChange={setBanked} /></Field>
        {preview.isLoading && <Skeleton className="h-32 w-full" />}
        {preview.error && <Alert tone="bad">{preview.error.message} <button className="underline" onClick={() => void preview.refetch()}>{t("retry")}</button></Alert>}
        {already && <Alert tone="warn">{t("alreadyClosed", { status: t(`closeStatuses.${p.close.status}`, p.close.status) })}</Alert>}
        {p && p.problems.length > 0 && <Alert tone="warn"><ul className="list-disc space-y-1 pl-5">{p.problems.map((x) => <li key={x}>{x}</li>)}</ul></Alert>}
        {p && lines.length > 0 && (
          <dl className="divide-y divide-line rounded-lg border border-line text-sm">
            {lines.map((l) => (
              <div key={l.path.join(".")} className="flex justify-between gap-3 px-3 py-2">
                <dt className="text-muted">{label(l.path)}</dt>
                <dd className="tnum font-medium">{l.value === "" ? "—" : looksNumeric(l.value) ? money(l.value, company?.currency) : l.value}</dd>
              </div>
            ))}
          </dl>
        )}
        {hasVariance && !already && (
          <Field label={t("explanation")} required hint={t("explanationHint")}><Textarea value={why} onChange={(e) => setWhy(e.target.value)} maxLength={2000} /></Field>
        )}
      </div>
      <ConfirmDialog open={confirming} onClose={() => setConfirming(false)} onConfirm={() => submit.mutate()} busy={submit.isPending}
        title={t("closeAndLock")} confirmLabel={t("closeAndLock")} message={t("closeAsk", { date: formatDate(date) })} />
    </Drawer>
  );
}
