import { Banknote, ClipboardCheck, FilePlus2, Pencil, Plus, StickyNote, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, Attachments, Button, ConfirmDialog, EmptyState, ErrorState, Menu, PageHeader, Skeleton, Tabs, unwrap, useCan, useTranslation } from "@/sdk";
import { jobHref } from "@/modules/jobs/public";

import { AnswerDialog } from "../components/AnswerDialog";
import { AuthorityDialog, CloseDialog, CompletionDialog, EditDialog, NoteDialog, WorkDecisionDialog, type ClaimDialog } from "../components/ClaimDialogs";
import { CounterDialog, CustomerDecisionDialog, ReductionDialog } from "../components/DecisionDialogs";
import { EstimateCard, type EstimateHandlers } from "../components/EstimateCard";
import { EstimateEditor, type EditorTarget } from "../components/EstimateEditor";
import { LinksDialog } from "../components/LinksDialog";
import { MoneyTab } from "../components/MoneyTab";
import { SendDialog } from "../components/SendDialog";
import { ClaimStatusBadge } from "../components/StatusBits";
import { SummaryCard } from "../components/SummaryCard";
import { TimelineTab } from "../components/TimelineTab";
import { openPrintable, useClaim, useClaimsCompany, useClaimsMutation, usePayers } from "../hooks";
import type { Estimate, EstimateLine } from "../types";

type Tab = "estimates" | "money" | "timeline" | "files";

/** One claim: the estimates with the payer's answers beside each line, the money, the timeline and the photos. */
export default function ClaimPage() {
  const { claimId = "" } = useParams();
  const { t } = useTranslation("claims");
  const { currency } = useClaimsCompany();
  const claimQuery = useClaim(claimId);
  const claim = claimQuery.data;
  const payers = usePayers(claim?.company_id ?? "");
  const payer = payers.data?.find((p) => p.id === claim?.payer_id);
  const canEstimate = useCan("claims.estimate");
  const canManage = useCan("claims.manage");
  const canInvoice = useCan("claims.invoice");
  const canPay = useCan("claims.payments");
  const [tab, setTab] = useState<Tab>("estimates");
  const [showOld, setShowOld] = useState(false);
  const [editor, setEditor] = useState<EditorTarget | null>(null);
  const [sending, setSending] = useState<Estimate | null>(null);
  const [answering, setAnswering] = useState<Estimate | null>(null);
  const [linking, setLinking] = useState<Estimate | null>(null);
  const [withdrawing, setWithdrawing] = useState<Estimate | null>(null);
  const [counter, setCounter] = useState<EstimateLine | null>(null);
  const [customerLine, setCustomerLine] = useState<EstimateLine | null>(null);
  const [reducing, setReducing] = useState<EstimateLine | null>(null);
  const [dialog, setDialog] = useState<ClaimDialog>(null);

  const revise = useClaimsMutation((e: Estimate) => unwrap(api.POST("/api/v1/claims/claims/{claim_id}/estimates", { params: { path: { claim_id: claimId } }, body: { kind: "revision", from_estimate_id: e.id, apply_payer_terms: false } })),
    { onDone: (made) => setEditor({ estimate: made, kind: "original" }) });
  const withdraw = useClaimsMutation((e: Estimate) => unwrap(api.POST("/api/v1/claims/estimates/{estimate_id}/withdraw", { params: { path: { estimate_id: e.id } }, body: {} })),
    { done: t("estimate.withdrawn"), onDone: () => setWithdrawing(null) });

  const { live, old, latestOf } = useMemo(() => {
    const all = claim?.estimates ?? [];
    const latest = new Map<string, number>();
    for (const e of all) if (e.status !== "withdrawn") latest.set(e.lineage_id, Math.max(latest.get(e.lineage_id) ?? 0, e.seq));
    return {
      live: all.filter((e) => e.in_play || e.status === "draft"),
      old: all.filter((e) => !(e.in_play || e.status === "draft")).reverse(),
      latestOf: (e: Estimate) => latest.get(e.lineage_id) === e.seq,
    };
  }, [claim?.estimates]);

  if (claimQuery.isLoading) return <Skeleton className="h-96" />;
  if (claimQuery.error || !claim) return <ErrorState message={claimQuery.error?.message} onRetry={() => void claimQuery.refetch()} />;

  const closed = claim.status === "closed";
  const draft = claim.estimates.find((e) => e.status === "draft");
  const hasOriginal = claim.estimates.some((e) => e.lineage_kind === "original" && e.status !== "withdrawn");
  const handlers: EstimateHandlers = {
    onEdit: (e) => setEditor({ estimate: e, kind: "original" }),
    onSend: setSending, onAnswer: setAnswering, onRevise: (e) => revise.mutate(e), onLinks: setLinking,
    onPrint: (e) => { void openPrintable(e.id); }, onWithdraw: setWithdrawing,
    onCounter: setCounter, onCustomer: setCustomerLine, onReduce: setReducing,
  };

  const primary = (() => {
    if (closed) return null;
    if (draft && canEstimate) return <Button onClick={() => setEditor({ estimate: draft, kind: "original" })}><Pencil className="h-4 w-4" />{t("page.continueDraft")}</Button>;
    if (!hasOriginal && canEstimate) return <Button onClick={() => setEditor({ estimate: null, kind: "original" })}><FilePlus2 className="h-4 w-4" />{t("page.writeEstimate")}</Button>;
    if (claim.status === "authorised" && canManage) return <Button onClick={() => setDialog("complete")}><ClipboardCheck className="h-4 w-4" />{t("page.signOff")}</Button>;
    if ((claim.status === "completed" || claim.can_invoice) && canInvoice) return <Button onClick={() => setTab("money")}><Banknote className="h-4 w-4" />{t("page.invoice")}</Button>;
    if (claim.status === "invoiced" && canPay) return <Button onClick={() => setTab("money")}><Banknote className="h-4 w-4" />{t("page.recordPayment")}</Button>;
    return null;
  })();

  return (
    <>
      <PageHeader
        back={{ to: "/claims", label: t("menu.claims") }}
        title={<span className="inline-flex flex-wrap items-center gap-2">{claim.number}<ClaimStatusBadge status={claim.status} reason={claim.closed_reason} /></span>}
        description={<span>{[claim.subject, claim.payer_name, claim.insured_name].filter(Boolean).join(" · ")}{claim.source_type === "job" && claim.source_id && <> · <Link className="underline" to={jobHref(claim.source_id)}>{t("page.job", { number: claim.source_number ?? "" })}</Link></>}{claim.source_type === "appointment" && claim.source_number ? ` · ${claim.source_number}` : ""}</span>}
        actions={<>
          {primary}
          {!closed && (
            <Menu label={t("page.more")} trigger={<span className="inline-flex h-9 items-center rounded-lg border border-line bg-surface px-3 text-sm shadow-card">{t("page.more")}</span>}
              items={[
                ...(canEstimate && hasOriginal && !draft ? [{ label: t("page.supplementary"), icon: <Plus className="h-4 w-4" />, onSelect: () => setEditor({ estimate: null, kind: "supplementary" }) }] : []),
                ...(canManage ? [
                  { label: t("page.editDetails"), icon: <Pencil className="h-4 w-4" />, onSelect: () => setDialog("edit") },
                  { label: t("page.addNote"), icon: <StickyNote className="h-4 w-4" />, onSelect: () => setDialog("note") },
                  ...(claim.status !== "completed" && claim.status !== "invoiced" && claim.status !== "settled" ? [{ label: t("page.signOff"), icon: <ClipboardCheck className="h-4 w-4" />, onSelect: () => setDialog("complete") }] : []),
                  { label: t("page.close"), icon: <X className="h-4 w-4" />, danger: true, onSelect: () => setDialog("close") },
                ] : []),
              ]} />
          )}
        </>} />
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="min-w-0">
          <Tabs<Tab> value={tab} onChange={setTab} tabs={[
            { id: "estimates", label: t("page.tabs.estimates"), count: claim.estimates.length },
            { id: "money", label: t("page.tabs.money"), count: claim.runs.length || undefined },
            { id: "timeline", label: t("page.tabs.timeline") },
            { id: "files", label: t("page.tabs.files") },
          ]} />
          {tab === "estimates" && (
            <div className="space-y-4">
              {claim.estimates.length === 0 ? (
                <EmptyState title={t("page.noEstimate")} hint={t("page.noEstimateHint")}
                  action={canEstimate && !closed ? <Button onClick={() => setEditor({ estimate: null, kind: "original" })}><FilePlus2 className="h-4 w-4" />{t("page.writeEstimate")}</Button> : undefined} />
              ) : (
                <>
                  {live.map((e) => <EstimateCard key={e.id} estimate={e} currency={currency} canEstimate={canEstimate} canInvoice={canInvoice} closed={closed} handlers={handlers} latest={latestOf(e)} />)}
                  {old.length > 0 && (
                    <div>
                      <Button variant="ghost" size="sm" onClick={() => setShowOld(!showOld)}>{showOld ? t("page.hideOld") : t("page.showOld", { n: old.length })}</Button>
                      {showOld && <div className="mt-3 space-y-4">{old.map((e) => <EstimateCard key={e.id} estimate={e} currency={currency} canEstimate={false} canInvoice={false} closed handlers={handlers} latest={false} />)}</div>}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
          {tab === "money" && <MoneyTab claim={claim} currency={currency} canInvoice={canInvoice} canPay={canPay} />}
          {tab === "timeline" && <TimelineTab claim={claim} />}
          {tab === "files" && <Attachments entityType="claims.claim" entityId={claim.id} />}
        </div>
        <SummaryCard claim={claim} currency={currency} canManage={canManage} onAuthority={() => setDialog("authority")} onWorkDecision={() => setDialog("work")} />
      </div>

      <EstimateEditor claimId={claim.id} target={editor} payer={payer} currency={currency} onClose={() => setEditor(null)} />
      <SendDialog estimate={sending} claim={claim} payer={payer} onClose={() => setSending(null)} />
      <AnswerDialog estimate={answering} claim={claim} currency={currency} onClose={() => setAnswering(null)} />
      <LinksDialog estimate={linking} onClose={() => setLinking(null)} />
      <CounterDialog line={counter} claim={claim} currency={currency} onClose={() => setCounter(null)} />
      <CustomerDecisionDialog line={customerLine} claim={claim} currency={currency} onClose={() => setCustomerLine(null)} />
      <ReductionDialog line={reducing} claim={claim} currency={currency} onClose={() => setReducing(null)} />
      <ConfirmDialog open={withdrawing !== null} onClose={() => setWithdrawing(null)} danger busy={withdraw.isPending}
        title={withdrawing?.status === "draft" ? t("estimate.discardTitle") : t("estimate.withdrawTitle")} message={withdrawing?.status === "draft" ? t("estimate.discardMessage") : t("estimate.withdrawMessage")}
        confirmLabel={withdrawing?.status === "draft" ? t("estimate.discard") : t("estimate.withdraw")} onConfirm={() => withdrawing && withdraw.mutate(withdrawing)} />
      {dialog === "authority" && <AuthorityDialog claim={claim} onClose={() => setDialog(null)} />}
      {dialog === "complete" && <CompletionDialog claim={claim} onClose={() => setDialog(null)} />}
      {dialog === "note" && <NoteDialog claim={claim} onClose={() => setDialog(null)} />}
      {dialog === "close" && <CloseDialog claim={claim} onClose={() => setDialog(null)} />}
      {dialog === "work" && <WorkDecisionDialog claim={claim} onClose={() => setDialog(null)} />}
      {dialog === "edit" && <EditDialog claim={claim} onClose={() => setDialog(null)} />}
    </>
  );
}
