import { Check, FileUp, Trash2, Undo2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  api, Alert, Button, Card, Checkbox, ConfirmDialog, DataTable, ErrorState, formatDate, Input, money, PageHeader, Skeleton, Stat, StatusBadge, toast, today, unwrap, useCan,
  useMutation, useQuery, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

import { isZero } from "../lib";
import { useScope } from "../scope";
import { StatementImport } from "../components/StatementImport";

type Line = Schemas["ReconLineOut"];

/** One reconciliation: tick the ledger lines that appear on the statement until the difference is zero, then complete it (final). */
export default function ReconciliationPage() {
  const { t } = useTranslation("finance");
  const { reconId = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const scope = useScope();
  const canReconcile = useCan("bank.reconcile");
  const key = ["finance", "recon", reconId];
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [until, setUntil] = useState(today());
  const [importing, setImporting] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const recon = useQuery({ queryKey: key, queryFn: () => unwrap(api.GET("/api/v1/finance/bank-reconciliations/{recon_id}", { params: { path: { recon_id: reconId } } })) });
  const r = recon.data;
  const currency = scope.companies.find((c) => c.id === r?.company_id)?.currency ?? scope.currency;
  const open = r?.status === "in_progress" && canReconcile;

  const clear = useMutation({
    mutationFn: (body: { line_ids?: string[]; until?: string; cleared: boolean }) => unwrap(api.POST("/api/v1/finance/bank-reconciliations/{recon_id}/clear", { params: { path: { recon_id: reconId } }, body })),
    onSuccess: (data) => { qc.setQueryData(key, data); setPicked(new Set()); void qc.invalidateQueries({ queryKey: ["finance", "recons"] }); },
  });
  const complete = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/finance/bank-reconciliations/{recon_id}/complete", { params: { path: { recon_id: reconId } } })),
    onSuccess: (data) => { qc.setQueryData(key, data); void qc.invalidateQueries({ queryKey: ["finance", "recons"] }); toast(t("bank.completed"), "ok"); setCompleting(false); },
    onError: () => setCompleting(false),
  });
  const discard = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/v1/finance/bank-reconciliations/{recon_id}", { params: { path: { recon_id: reconId } } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["finance", "recons"] }); toast(t("bank.discarded"), "ok"); navigate("/finance/bank"); },
    onError: () => setDiscarding(false),
  });

  if (recon.error) return <ErrorState title={t("bank.notFound")} message={recon.error.message} onRetry={() => void recon.refetch()} />;
  if (!r) return <Skeleton className="h-48 w-full" />;
  const toggle = (id: string) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const zero = isZero(r.difference);

  const table = (rows: Line[], cleared: boolean) => (
    <DataTable dense rows={rows} rowKey={(l) => l.line_id} pageSize={50}
      searchText={(l) => `${l.number} ${l.description ?? ""}`} searchPlaceholder={t("bank.searchLines")}
      empty={{ title: cleared ? t("bank.noneCleared") : t("bank.noneWaiting") }}
      toolbar={open && rows.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setPicked(new Set(rows.map((l) => l.line_id)))}>{t("bank.selectAll")}</Button>
          <Button size="sm" disabled={![...picked].some((id) => rows.some((l) => l.line_id === id))} loading={clear.isPending}
            onClick={() => clear.mutate({ line_ids: rows.filter((l) => picked.has(l.line_id)).map((l) => l.line_id), cleared: !cleared })}>
            {cleared ? <><Undo2 className="h-4 w-4" />{t("bank.unmatch")}</> : <><Check className="h-4 w-4" />{t("bank.markCleared")}</>}
          </Button>
        </div>) : undefined}
      columns={[
        ...(open ? [{ header: "✓", className: "w-10", cell: (l: Line) => <Checkbox aria-label={l.number} checked={picked.has(l.line_id)} onChange={() => toggle(l.line_id)} label="" /> }] : []),
        { header: t("date"), sortValue: (l) => l.entry_date, cell: (l) => formatDate(l.entry_date) },
        { header: t("number"), cell: (l) => <span className="font-mono text-xs">{l.number}</span> },
        { header: t("description"), hideBelow: "md", cell: (l) => l.description ?? "—" },
        { header: t("bank.amount"), align: "right", sortValue: (l) => Number(l.amount), cell: (l) => <span className={Number(l.amount) < 0 ? "text-bad" : ""}>{money(l.amount, currency)}</span> },
      ]} />
  );

  return (
    <>
      <PageHeader back={{ to: "/finance/bank", label: t("bank.title") }} title={`${r.account_code} · ${r.account_name}`}
        description={<span className="flex items-center gap-2">{t("bank.statementOf", { date: formatDate(r.statement_date) })}<StatusBadge status={r.status} /></span>}
        actions={open && <>
          <Button variant="secondary" onClick={() => setImporting(true)}><FileUp className="h-4 w-4" />{t("bank.import")}</Button>
          <Button variant="secondary" onClick={() => setDiscarding(true)}><Trash2 className="h-4 w-4" />{t("bank.discard")}</Button>
          <Button disabled={!zero} onClick={() => setCompleting(true)}><Check className="h-4 w-4" />{t("bank.complete")}</Button>
        </>} />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label={t("bank.statementBalance")} value={money(r.statement_balance, currency)} />
        <Stat label={t("bank.clearedBalance")} value={money(r.cleared_balance, currency)} />
        <Stat label={t("bank.difference")} value={money(r.difference, currency)} tone={zero ? "ok" : "bad"} hint={zero ? t("bank.differenceZero") : t("bank.differenceHint")} />
        <Stat label={t("bank.bookBalance")} value={money(r.book_balance, currency)} />
        <Stat label={t("bank.outstanding")} value={money(r.outstanding, currency)} hint={t("bank.outstandingHint")} />
      </div>
      {r.status === "completed" && <Alert tone="ok" className="mb-4">{t("bank.finalHint", { date: formatDate(r.completed_at, true) })}</Alert>}
      {open && !zero && <Alert tone="warn" className="mb-4">{t("bank.workHint")}</Alert>}
      <div className="space-y-4">
        <Card title={t("bank.waiting", { count: r.uncleared.length })} description={t("bank.waitingHint")} flush
          actions={open && (
            <div className="flex items-center gap-2">
              <Input type="date" aria-label={t("bank.clearUntil")} className="w-auto" value={until} onChange={(e) => setUntil(e.target.value)} />
              <Button variant="secondary" size="sm" loading={clear.isPending} onClick={() => clear.mutate({ until, cleared: true })}>{t("bank.clearUntil")}</Button>
            </div>)}>
          {table(r.uncleared, false)}
        </Card>
        <Card title={t("bank.onStatement", { count: r.cleared.length })} flush>{table(r.cleared, true)}</Card>
      </div>
      <p className="mt-3 text-xs text-muted">{t("bank.chargesHint")} <Link className="underline" to="/finance/expenses">{t("expenses.title")}</Link> · <Link className="underline" to="/finance/manual-journals/new">{t("journal.newManual")}</Link></p>
      <StatementImport open={importing} onClose={() => setImporting(false)} reconId={reconId} currency={currency} onApplied={(data) => { qc.setQueryData(key, data); void qc.invalidateQueries({ queryKey: ["finance", "recons"] }); }} />
      <ConfirmDialog open={completing} onClose={() => setCompleting(false)} busy={complete.isPending} title={t("bank.complete")} confirmLabel={t("bank.complete")} message={t("bank.completeAsk")} onConfirm={() => complete.mutate()} />
      <ConfirmDialog open={discarding} onClose={() => setDiscarding(false)} busy={discard.isPending} danger title={t("bank.discard")} confirmLabel={t("bank.discard")} message={t("bank.discardAsk")} onConfirm={() => discard.mutate()} />
    </>
  );
}
