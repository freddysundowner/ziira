import { Play, Upload } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, Card, DataTable, Drawer, Field, formatDate, Pager, PageHeader, Select, Tabs, Textarea, toast, unwrap, useCan, useMutation, usePagedList,
  useQuery, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

import { Amount } from "../components/Amount";
import { MatchPayment } from "../components/MatchPayment";
import { UploadStatement } from "../components/UploadStatement";
import { usePaymentAccounts } from "../components/usePaymentAccounts";
import { matchTone } from "../logic";

const MATCH_STATUSES = ["unmatched", "proposed", "matched", "ignored"] as const;

/** What the provider or bank reported against what the business recorded: match them, ignore what is not ours. */
export default function ReconciliationPage() {
  const { t } = useTranslation("payments");
  const qc = useQueryClient();
  const canMatch = useCan("recon.match");
  const canUpload = useCan("payments.record");
  const [tab, setTab] = useState<"transactions" | "matches">("transactions");
  const [uploading, setUploading] = useState(false);
  const run = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/payments/matching/run", { body: {} })),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["transactions"] });
      void qc.invalidateQueries({ queryKey: ["matches"] });
      toast(t("matchingRan", { applied: r.applied, proposed: r.proposed, flagged: r.flagged }), "ok");
    },
  });
  return (
    <>
      <PageHeader title={t("reconTitle")} description={t("reconHint")}
        actions={
          <>
            {canUpload && <Button variant="secondary" onClick={() => setUploading(true)}><Upload className="h-4 w-4" />{t("uploadStatement")}</Button>}
            {canMatch && <Button loading={run.isPending} onClick={() => run.mutate()}><Play className="h-4 w-4" />{t("runMatching")}</Button>}
          </>
        } />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "transactions", label: t("transactions") }, { id: "matches", label: t("matches") }]} />
      {tab === "transactions" ? <Transactions canMatch={canMatch} /> : <Matches canMatch={canMatch} />}
      <UploadStatement open={uploading} onClose={() => setUploading(false)} />
    </>
  );
}

function Transactions({ canMatch }: { canMatch: boolean }) {
  const { t } = useTranslation("payments");
  const qc = useQueryClient();
  const [status, setStatus] = useState("unmatched");
  const [accountId, setAccountId] = useState("");
  const [matching, setMatching] = useState<Schemas["ExternalOut"] | null>(null);
  const [ignoring, setIgnoring] = useState<{ txn: Schemas["ExternalOut"]; undo: boolean } | null>(null);
  const [reason, setReason] = useState("");
  const accounts = usePaymentAccounts({ includeInactive: true });
  const list = usePagedList(["transactions", status, accountId], (limit, offset) =>
    unwrap(api.GET("/api/v1/payments/transactions", { params: { query: { match_status: status || undefined, payment_account_id: accountId || undefined, limit, offset } } })));
  const toggle = useMutation({
    mutationFn: () => {
      if (!ignoring) throw new Error("Nothing selected");
      const path = { txn_id: ignoring.txn.id };
      const body = { reason: reason.trim() };
      return ignoring.undo
        ? unwrap(api.POST("/api/v1/payments/transactions/{txn_id}/unignore", { params: { path }, body }))
        : unwrap(api.POST("/api/v1/payments/transactions/{txn_id}/ignore", { params: { path }, body }));
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["transactions"] }); toast(t("saved"), "ok"); setIgnoring(null); setReason(""); },
  });

  return (
    <>
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(x) => x.id}
        toolbar={
          <>
            <Select className="w-44" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>{MATCH_STATUSES.map((s) => <option key={s} value={s}>{t(`matchStatuses.${s}`)}</option>)}
            </Select>
            <Select className="w-48" aria-label={t("account")} value={accountId} onChange={(e) => setAccountId(e.target.value)}>
              <option value="">{t("allAccounts")}</option>{(accounts.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </Select>
          </>
        }
        empty={{ title: status === "unmatched" ? t("nothingUnmatched") : t("noTransactions"), hint: status === "unmatched" ? t("nothingUnmatchedHint") : t("noTransactionsHint") }}
        columns={[
          { header: t("when"), cell: (x) => formatDate(x.txn_time, true) },
          { header: t("reference"), cell: (x) => <span className="font-mono text-xs font-medium">{x.external_ref}</span> },
          { header: t("who"), hideBelow: "md", cell: (x) => <span>{x.counterparty_name ?? "—"}<span className="ml-1 text-xs text-muted">{x.counterparty_phone_masked}</span></span> },
          { header: t("account"), hideBelow: "lg", cell: (x) => accounts.data?.find((a) => a.id === x.payment_account_id)?.name ?? "—" },
          {
            header: t("amount"), align: "right",
            cell: (x) => <span className={x.direction === "out" ? "font-medium text-warn" : "font-medium"}>{x.direction === "out" ? "−" : ""}<Amount value={x.amount} companyId={accounts.data?.find((a) => a.id === x.payment_account_id)?.company_id} /></span>,
          },
          { header: t("status"), cell: (x) => <Badge tone={matchTone(x.match_status)}>{t(`matchStatuses.${x.match_status}`, x.match_status)}</Badge> },
          {
            header: "", align: "right",
            cell: (x) => canMatch && (
              <span className="inline-flex gap-1">
                {(x.match_status === "unmatched" || x.match_status === "proposed") && <Button size="sm" onClick={() => setMatching(x)}>{t("match")}</Button>}
                {(x.match_status === "unmatched" || x.match_status === "proposed") && <Button size="sm" variant="ghost" onClick={() => setIgnoring({ txn: x, undo: false })}>{t("ignore")}</Button>}
                {x.match_status === "ignored" && <Button size="sm" variant="ghost" onClick={() => setIgnoring({ txn: x, undo: true })}>{t("unignore")}</Button>}
              </span>
            ),
          },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <MatchPayment txn={matching} onClose={() => setMatching(null)} />
      <Drawer open={!!ignoring} onClose={() => setIgnoring(null)} title={ignoring?.undo ? t("unignore") : t("ignore")}
        footer={<><Button variant="secondary" onClick={() => setIgnoring(null)}>{t("cancel")}</Button><Button loading={toggle.isPending} disabled={!reason.trim()} onClick={() => toggle.mutate()}>{ignoring?.undo ? t("unignore") : t("ignore")}</Button></>}>
        <p className="mb-4 text-sm text-muted">{ignoring?.undo ? t("unignoreHint") : t("ignoreHint")}</p>
        <Field label={t("reason")} required><Textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} autoFocus /></Field>
      </Drawer>
    </>
  );
}

function Matches({ canMatch }: { canMatch: boolean }) {
  const { t } = useTranslation("payments");
  const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const [undoing, setUndoing] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const q = useQuery({ queryKey: ["matches", status], queryFn: () => unwrap(api.GET("/api/v1/payments/matches", { params: { query: { status: status || undefined } } })) });
  const confirm = useMutation({
    mutationFn: (m: Schemas["MatchOut"]) => unwrap(api.POST("/api/v1/payments/matches", { body: { external_transaction_id: m.external_transaction_id, payment_id: m.payment_id, amount: m.amount } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["matches"] }); void qc.invalidateQueries({ queryKey: ["transactions"] }); toast(t("matchSaved"), "ok"); },
  });
  const undo = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/payments/matches/{match_id}/undo", { params: { path: { match_id: undoing ?? "" } }, body: { reason: reason.trim() } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["matches"] }); void qc.invalidateQueries({ queryKey: ["transactions"] }); toast(t("matchUndone"), "ok"); setUndoing(null); setReason(""); },
  });
  return (
    <>
      <Card flush>
        <DataTable
          rows={q.data} loading={q.isLoading} error={q.error?.message} onRetry={() => void q.refetch()} rowKey={(m) => m.id} pageSize={20}
          toolbar={
            <Select className="w-44" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>{(["proposed", "applied", "undone"] as const).map((s) => <option key={s} value={s}>{t(`matchStatuses.${s}`)}</option>)}
            </Select>
          }
          empty={{ title: t("noMatchesYet"), hint: t("noMatchesYetHint") }}
          columns={[
            { header: t("amount"), align: "right", cell: (m) => <Amount value={m.amount} /> },
            { header: t("how"), cell: (m) => t(`stages.${m.stage}`, m.stage) },
            { header: t("rule"), hideBelow: "md", cell: (m) => m.rule_code ?? "—" },
            { header: t("confidence"), hideBelow: "lg", align: "right", cell: (m) => (m.confidence ? `${Math.round(Number(m.confidence) * 100)}%` : "—") },
            { header: t("status"), cell: (m) => <Badge tone={matchTone(m.status)}>{t(`matchStatuses.${m.status}`, m.status)}</Badge> },
            {
              header: "", align: "right",
              cell: (m) => canMatch && (
                <span className="inline-flex gap-1">
                  {m.status === "proposed" && <Button size="sm" loading={confirm.isPending && confirm.variables?.id === m.id} disabled={confirm.isPending} onClick={() => confirm.mutate(m)}>{t("confirm")}</Button>}
                  {m.status !== "undone" && <Button size="sm" variant="ghost" onClick={() => setUndoing(m.id)}>{t("undo")}</Button>}
                </span>
              ),
            },
          ]}
        />
      </Card>
      <Drawer open={!!undoing} onClose={() => setUndoing(null)} title={t("undoMatch")}
        footer={<><Button variant="secondary" onClick={() => setUndoing(null)}>{t("cancel")}</Button><Button variant="danger" loading={undo.isPending} disabled={!reason.trim()} onClick={() => undo.mutate()}>{t("undo")}</Button></>}>
        <p className="mb-4 text-sm text-muted">{t("undoMatchHint")}</p>
        <Field label={t("reason")} required><Textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} autoFocus /></Field>
      </Drawer>
    </>
  );
}
