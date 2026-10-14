import { useState } from "react";

import { api, Alert, Badge, Button, DataTable, Field, formatDate, humanise, Modal, money, Textarea, toast, unwrap, useMutation, useTranslation, type Schemas } from "@/sdk";

type Result = Schemas["SuggestResultOut"];

/** Paste or load a bank statement (CSV: date, reference, description, amount), see which lines match the books, then apply the matches. */
export function StatementImport({ open, onClose, reconId, currency, onApplied }: {
  open: boolean; onClose: () => void; reconId: string; currency?: string; onApplied: (data: Result["reconciliation"]) => void;
}) {
  const { t } = useTranslation("finance");
  const [csv, setCsv] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const run = useMutation({
    mutationFn: (apply: boolean) => unwrap(api.POST("/api/v1/finance/bank-reconciliations/{recon_id}/suggestions", { params: { path: { recon_id: reconId } }, body: { csv, apply } })),
    onSuccess: (data, apply) => {
      setResult(data);
      if (apply) {
        onApplied(data.reconciliation);
        toast(t("bank.applied", { count: data.suggestions.length }), "ok");
        close();
      }
    },
  });
  const close = () => { setCsv(""); setResult(null); onClose(); };

  async function load(file: File | undefined) {
    if (!file) return;
    setCsv(await file.text());
    setResult(null);
  }

  return (
    <Modal open={open} onClose={close} title={t("bank.import")} size="lg"
      footer={<>
        <Button variant="secondary" onClick={close}>{t("cancel")}</Button>
        {result && result.suggestions.length > 0
          ? <Button loading={run.isPending} onClick={() => run.mutate(true)}>{t("bank.applyMatches", { count: result.suggestions.length })}</Button>
          : <Button loading={run.isPending} disabled={!csv.trim()} onClick={() => run.mutate(false)}>{t("bank.findMatches")}</Button>}
      </>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("bank.importHint")}</p>
        <Field label={t("bank.statementFile")}><input type="file" accept=".csv,text/csv,text/plain" className="block w-full text-sm" onChange={(e) => void load(e.target.files?.[0])} /></Field>
        <Field label={t("bank.statementText")} hint="date,reference,description,amount">
          <Textarea className="font-mono text-xs" rows={6} value={csv} onChange={(e) => { setCsv(e.target.value); setResult(null); }} />
        </Field>
        {result && (
          <div className="space-y-3">
            {result.suggestions.length === 0 && <Alert tone="warn">{t("bank.noMatches")}</Alert>}
            {result.suggestions.length > 0 && (
              <DataTable dense rows={result.suggestions} rowKey={(s) => s.ledger.line_id} empty={{ title: "" }}
                columns={[
                  { header: t("bank.onStatementLine"), cell: (s) => <div><p>{formatDate(s.statement.date)} · {s.statement.description || s.statement.reference || "—"}</p><p className="text-xs text-muted">{money(s.statement.amount, currency)}</p></div> },
                  { header: t("bank.inBooks"), cell: (s) => <div><p className="font-mono text-xs">{s.ledger.number}</p><p className="text-xs text-muted">{formatDate(s.ledger.entry_date)} · {money(s.ledger.amount, currency)}</p></div> },
                  { header: t("bank.why"), hideBelow: "sm", cell: (s) => <Badge>{humanise(s.reason)}</Badge> },
                ]} />
            )}
            {result.unmatched.length > 0 && (
              <div>
                <h3 className="mb-1 text-sm font-semibold">{t("bank.unmatched", { count: result.unmatched.length })}</h3>
                <p className="mb-2 text-xs text-muted">{t("bank.unmatchedHint")}</p>
                <DataTable dense rows={result.unmatched} rowKey={(u) => `${u.date}-${u.reference}-${u.amount}-${u.description}`} empty={{ title: "" }}
                  columns={[
                    { header: t("date"), cell: (u) => formatDate(u.date) },
                    { header: t("description"), cell: (u) => u.description || u.reference || "—" },
                    { header: t("bank.amount"), align: "right", cell: (u) => money(u.amount, currency) },
                  ]} />
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
