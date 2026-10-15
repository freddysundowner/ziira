import { type ChangeEvent, type FormEvent, useState } from "react";

import {
  Alert, api, Badge, type BadgeTone, Button, Card, DataTable, Field, FormGrid, formatDate, humanise, Input, money, NumberInput, Stat, Textarea, toast, unwrap,
  useCan, useCurrency, useMutation, useTranslation,
} from "@/sdk";

import type { StatementRecon } from "../types";

const TONE: Record<string, BadgeTone> = { matched: "ok", amount_differs: "warn", missing_here: "bad" };

/** Check a supplier's own statement against our books. Nothing is changed: it is a report. */
export function SupplierReconcileTab({ supplierId, companyId }: { supplierId: string; companyId: string }) {
  const { t } = useTranslation("purchasing");
  const currency = useCurrency(companyId);
  const canRun = useCan("bills.manage");
  const [csv, setCsv] = useState("");
  const [theirBalance, setTheirBalance] = useState("");
  const [asOf, setAsOf] = useState("");
  const run = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/purchasing/suppliers/{supplier_id}/statement-reconciliation", { params: { path: { supplier_id: supplierId } }, body: {
      csv, their_balance: theirBalance || null, as_of: asOf || null } })),
    onError: (e) => toast((e as Error).message, "bad"),
  });

  async function load(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) setCsv(await file.text());
    e.target.value = "";
  }
  const submit = (e: FormEvent) => { e.preventDefault(); run.mutate(); };
  if (!canRun) return <Alert tone="info">{t("noReconcilePermission")}</Alert>;

  return (
    <div className="space-y-4">
      <Card title={t("reconcileTitle")} description={t("reconcileHint")}>
        <form onSubmit={submit} className="space-y-4">
          <Field label={t("statementText")} hint={t("statementFormat")} required>
            <Textarea className="min-h-[160px] font-mono text-xs" value={csv} onChange={(e) => setCsv(e.target.value)} placeholder={"date,reference,kind,amount\n2025-01-31,INV-1001,invoice,12500.00"} />
          </Field>
          <FormGrid cols={3}>
            <Field label={t("theirBalance")} hint={t("theirBalanceHint")}><NumberInput value={theirBalance} onChange={setTheirBalance} /></Field>
            <Field label={t("asOf")} hint={t("asOfHint")}><Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></Field>
            <Field label={t("orUploadFile")}><Input type="file" accept=".csv,text/csv,text/plain" onChange={(e) => void load(e)} /></Field>
          </FormGrid>
          <Button type="submit" loading={run.isPending} disabled={!csv.trim()}>{t("compare")}</Button>
        </form>
      </Card>
      {run.data && <Result result={run.data} currency={currency} />}
    </div>
  );
}

function Result({ result, currency }: { result: StatementRecon; currency?: string }) {
  const { t } = useTranslation("purchasing");
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={t("theirBalance")} value={money(result.their_balance, currency)} />
        <Stat label={t("ourBalance")} value={money(result.our_balance, currency)} />
        <Stat label={t("difference")} value={money(result.difference, currency)} tone={Number(result.difference) === 0 ? "ok" : "bad"} hint={t("explainedBy", { amount: money(result.explained_by_lines, currency) })} />
        <Stat label={t("unexplained")} value={money(result.unexplained, currency)} tone={Number(result.unexplained) === 0 ? "ok" : "bad"} />
      </div>
      <div className="flex flex-wrap gap-2">{Object.entries(result.summary).map(([k, v]) => <Badge key={k} tone={TONE[k] ?? "neutral"}>{t(`recon.${k}`, humanise(k))}: {v}</Badge>)}</div>
      <Card title={t("theirLines")} flush>
        <DataTable rows={result.items} rowKey={(i) => `${i.date}${i.kind}${i.reference}`} empty={{ title: t("noLines") }}
          columns={[
            { header: t("date"), cell: (i) => formatDate(i.date) },
            { header: t("type"), cell: (i) => t(`docKind.${i.kind}`, humanise(i.kind)) },
            { header: t("theirRef"), cell: (i) => <span className="font-mono text-xs">{i.reference}</span> },
            { header: t("theirAmount"), align: "right", cell: (i) => money(i.their_amount, currency) },
            { header: t("ourAmount"), align: "right", hideBelow: "sm", cell: (i) => money(i.our_amount, currency) },
            { header: t("result"), cell: (i) => <Badge tone={TONE[i.status] ?? "neutral"}>{t(`recon.${i.status}`, humanise(i.status))}</Badge> },
            { header: t("note"), hideBelow: "lg", cell: (i) => i.note },
          ]} />
      </Card>
      {result.missing_there.length > 0 && (
        <Card title={t("missingThere")} description={t("missingThereHint")} flush>
          <DataTable rows={result.missing_there} rowKey={(i) => `${i.date}${i.kind}${i.reference}`} empty={{ title: "" }}
            columns={[
              { header: t("date"), cell: (i) => formatDate(i.date) },
              { header: t("type"), cell: (i) => t(`docKind.${i.kind}`, humanise(i.kind)) },
              { header: t("number"), cell: (i) => <span className="font-mono text-xs">{i.reference}</span> },
              { header: t("amount"), align: "right", cell: (i) => money(i.amount, currency) },
              { header: t("note"), hideBelow: "md", cell: (i) => i.note },
            ]} />
        </Card>
      )}
    </>
  );
}
