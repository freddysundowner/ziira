import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  api, Alert, Badge, Button, Card, ConfirmDialog, Field, FormGrid, Input, PageHeader, Select, money, today, toast, unwrap, useFormState, useMutation, useQueryClient, useTranslation, useUnsavedWarning,
} from "@/sdk";

import { accountOptions, useAccounts } from "../api";
import { blankLine, type EditorLine, JournalLinesEditor } from "../components/JournalLinesEditor";
import { previewJournal } from "../lib";
import { useScope } from "../scope";

/** Write a manual journal: lines with a live debit / credit / difference display. It can only be saved when it balances. */
export default function NewManualJournalPage() {
  const { t } = useTranslation("finance");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const scope = useScope();
  const accounts = useAccounts(scope.companyId);
  const f = useFormState({ entry_date: today(), description: "" });
  const [lines, setLines] = useState<EditorLine[]>(() => [blankLine(), blankLine()]);
  const [confirming, setConfirming] = useState(false);
  const preview = useMemo(() => previewJournal(lines), [lines]);
  useUnsavedWarning(f.dirty || preview.debit !== "0.00" || preview.credit !== "0.00");

  const save = useMutation({
    meta: { silent: true },
    mutationFn: async (submit: boolean) => {
      const created = await unwrap(api.POST("/api/v1/finance/manual-journals", { body: {
        company_id: scope.companyId, entry_date: f.values.entry_date, description: f.values.description.trim(),
        lines: lines.filter((l) => l.account_id).map((l) => ({
          account_id: l.account_id, debit: l.debit || "0", credit: l.credit || "0", branch_id: l.branch_id || null, description: l.description.trim() || null })) } }));
      if (submit) {
        try {
          const sent = await unwrap(api.POST("/api/v1/finance/manual-journals/{manual_id}/submit", { params: { path: { manual_id: created.id } } }));
          return { id: created.id, status: sent.status };
        } catch (e) {
          toast((e as Error).message, "bad");
        }
      }
      return { id: created.id, status: created.status };
    },
    onSuccess: ({ id, status }) => {
      setConfirming(false);
      void qc.invalidateQueries({ queryKey: ["finance"] });
      toast(status === "posted" ? t("manual.posted") : status === "pending_approval" ? t("manual.sent") : t("manual.savedDraft"), "ok");
      navigate(`/finance/manual-journals/${id}`);
    },
    onError: (e) => { setConfirming(false); f.fail(e); toast((e as Error).message, "bad"); },
  });

  const c = scope.currency;
  const ready = preview.ready && !!f.values.description.trim() && !!scope.companyId;
  return (
    <>
      <PageHeader back={{ to: "/finance/journal", label: t("journal.title") }} title={t("manual.newTitle")} description={t("manual.newHint")} />
      <div className="space-y-4">
        <Card>
          <FormGrid cols={3}>
            {scope.companies.length > 1 && (
              <Field label={t("company")}><Select value={scope.companyId} onChange={(e) => scope.setCompany(e.target.value)}>{scope.companies.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</Select></Field>
            )}
            <Field label={t("date")} required error={f.error("entry_date")}><Input type="date" {...f.bind("entry_date")} required /></Field>
            <Field label={t("description")} required error={f.error("description")} className="sm:col-span-2"><Input {...f.bind("description")} maxLength={500} required /></Field>
          </FormGrid>
        </Card>
        <Card title={t("entry.lines")} description={t("manual.linesHint")}>
          <JournalLinesEditor lines={lines} onChange={setLines} accounts={accountOptions(accounts.data, { postable: true })} branches={scope.branches} />
        </Card>
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <dl className="tnum flex flex-wrap gap-x-8 gap-y-2 text-sm" aria-live="polite">
              <div><dt className="text-xs uppercase tracking-wide text-muted">{t("debit")}</dt><dd className="text-lg font-semibold">{money(preview.debit, c)}</dd></div>
              <div><dt className="text-xs uppercase tracking-wide text-muted">{t("credit")}</dt><dd className="text-lg font-semibold">{money(preview.credit, c)}</dd></div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted">{t("difference")}</dt>
                <dd className={`text-lg font-semibold ${preview.balanced ? "text-ok" : "text-bad"}`}>{money(preview.difference, c)}</dd>
              </div>
            </dl>
            {preview.balanced ? <Badge tone="ok">{t("balancedEntry")}</Badge> : <Badge tone="warn">{t("notBalancedYet")}</Badge>}
          </div>
          {preview.problems.length > 0 && preview.debit !== "0.00" && (
            <Alert tone="warn" className="mt-3"><ul className="list-disc pl-4">{preview.problems.map((p) => <li key={p}>{t(`problems.${p}`)}</li>)}</ul></Alert>
          )}
        </Card>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" onClick={() => navigate("/finance/journal")}>{t("cancel")}</Button>
          <Button variant="secondary" disabled={!ready || save.isPending} loading={save.isPending && save.variables === false} onClick={() => save.mutate(false)}>{t("manual.saveDraft")}</Button>
          <Button disabled={!ready || save.isPending} onClick={() => setConfirming(true)}>{t("manual.saveSubmit")}</Button>
        </div>
      </div>
      <ConfirmDialog open={confirming} onClose={() => setConfirming(false)} busy={save.isPending} title={t("manual.saveSubmit")} confirmLabel={t("manual.saveSubmit")}
        message={t("manual.submitAsk")} onConfirm={() => save.mutate(true)} />
    </>
  );
}
