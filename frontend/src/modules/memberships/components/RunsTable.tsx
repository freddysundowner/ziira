import { useState } from "react";

import {
  api, Badge, Button, ConfirmDialog, DataTable, Field, formatDate, Input, Modal, money, toast, unwrap, useCan, useCurrency, useMutation, useQuery,
  useQueryClient, useTranslation,
} from "@/sdk";

import type { Run } from "../hooks";
import { runTone } from "../logic";

const draftTotal = (r: Run): string => String(r.lines.reduce((sum, l) => sum + Number(l.quantity) * Number(l.unit_price) - Number(l.discount), 0));

/** The invoice attempts of a schedule, membership or package (or all that need review), with issue and discard for drafts and failures. */
export function RunsTable({ ownerId, status, companyId, empty }: { ownerId?: string; status?: string; companyId?: string; empty: { title: string; hint?: string } }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const currency = useCurrency(companyId);
  const canRecurring = useCan("recurring.manage");
  const canManage = useCan("memberships.manage");
  const canReview = canRecurring || canManage;
  const [discarding, setDiscarding] = useState<Run | null>(null);
  const [issuing, setIssuing] = useState<Run | null>(null);
  const [note, setNote] = useState("");
  const q = useQuery({
    queryKey: ["memberships", "runs", ownerId ?? "", status ?? ""],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/invoice-runs", { params: { query: { owner_id: ownerId, status: status as "failed" | undefined, limit: 100 } } })),
  });
  const done = () => { void qc.invalidateQueries({ queryKey: ["memberships"] }); };
  const issue = useMutation({
    meta: { silent: true },
    mutationFn: (run: Run) => unwrap(api.POST("/api/v1/memberships/invoice-runs/{run_id}/issue", { params: { path: { run_id: run.id } } })),
    onSuccess: (r) => { toast(t("invoiceIssued", { number: r.invoice_number ?? "" }), "ok"); setIssuing(null); done(); },
    onError: (e) => { toast((e as Error).message, "bad"); setIssuing(null); },
  });
  const discard = useMutation({
    meta: { silent: true },
    mutationFn: (run: Run) => unwrap(api.POST("/api/v1/memberships/invoice-runs/{run_id}/discard", { params: { path: { run_id: run.id } }, body: { note: note.trim() } })),
    onSuccess: () => { toast(t("periodDiscarded"), "ok"); setDiscarding(null); setNote(""); done(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const actionable = (r: Run) => r.status === "pending_review" || r.status === "failed";

  return (
    <>
      <DataTable rows={q.data} loading={q.isLoading} error={q.error?.message} onRetry={() => void q.refetch()} rowKey={(r) => r.id} dense empty={empty}
        columns={[
          { header: t("period"), sortValue: (r) => r.period_start, cell: (r) => <span className="font-medium">{formatDate(r.period_start)}</span> },
          ...(ownerId ? [] : [{ header: t("customer"), cell: (r: Run) => r.customer_name ?? "—" }]),
          { header: t("status"), cell: (r) => <Badge tone={runTone(r.status)}>{t(`runStatus.${r.status}`, r.status)}</Badge> },
          { header: t("invoice"), hideBelow: "sm", align: "right", cell: (r) => (r.invoice_number ? `${r.invoice_number} · ${money(r.total, currency)}` : r.status === "pending_review" ? money(draftTotal(r), currency) : "—") },
          { header: t("result"), hideBelow: "md", cell: (r) => <span className="text-muted">{r.message ?? "—"}</span> },
          ...(canReview ? [{ header: "", align: "right" as const, cell: (r: Run) => actionable(r) ? (
            <span className="flex justify-end gap-2">
              <Button size="sm" onClick={() => setIssuing(r)}>{r.status === "failed" ? t("tryAgain") : t("issueInvoice")}</Button>
              <Button size="sm" variant="secondary" onClick={() => { setNote(""); setDiscarding(r); }}>{t("discard")}</Button>
            </span>) : null }] : []),
        ]} />
      <ConfirmDialog open={!!issuing} onClose={() => setIssuing(null)} title={t("issueInvoice")} message={t("issueConfirm", { date: issuing ? formatDate(issuing.period_start) : "" })}
        confirmLabel={t("issueInvoice")} busy={issue.isPending} onConfirm={() => issuing && issue.mutate(issuing)} />
      <Modal open={!!discarding} onClose={() => setDiscarding(null)} title={t("discardTitle")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setDiscarding(null)}>{t("cancel")}</Button>
          <Button variant="danger" loading={discard.isPending} disabled={!note.trim()} onClick={() => discarding && discard.mutate(discarding)}>{t("discard")}</Button></>}>
        <p className="mb-3 text-sm text-muted">{t("discardExplain", { date: discarding ? formatDate(discarding.period_start) : "" })}</p>
        <Field label={t("whyDiscard")} required><Input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
      </Modal>
    </>
  );
}
