import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { customerPath } from "@/modules/crm/public";
import { invoiceHref } from "@/modules/pos/public";

import {
  Alert, api, Badge, Button, Card, ConfirmDialog, DetailList, ErrorState, Field, money, NumberInput, PageHeader, Select, Skeleton, Textarea, toast, unwrap, useCurrency, useMutation, useQuery, useTranslation,
} from "@/sdk";

import { NarrativeCard } from "../components/NarrativeCard";
import { PartnerReviewCard } from "../components/PartnerReviewCard";
import { ManualLineDialog, ReviewLines } from "../components/ReviewLines";
import { useRefresh, useSnippets } from "../hooks";
import { GROUPINGS, type Review, type ReviewLine } from "../types";

const ROUNDINGS = [0, 5, 6, 10, 15, 30, 60] as const;

/** An invoice review: check, adjust and issue the invoice for approved time and expenses. Nothing is invoiced until Issue. */
export default function ReviewPage() {
  const { t } = useTranslation("timebilling");
  const { reviewId = "" } = useParams();
  const navigate = useNavigate();
  const refresh = useRefresh();
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<ReviewLine | null>(null);
  const [regroup, setRegroup] = useState<{ group_by?: (typeof GROUPINGS)[number]; round_minutes?: (typeof ROUNDINGS)[number] } | null>(null);
  const [issuing, setIssuing] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [memo, setMemo] = useState("");
  const [days, setDays] = useState("");
  const [creditProblem, setCreditProblem] = useState(false);

  const review = useQuery<Review>({
    queryKey: ["timebilling", "review", reviewId],
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/invoice-reviews/{batch_id}", { params: { path: { batch_id: reviewId } } })),
  });
  const r = review.data;
  const snippets = useSnippets(r?.company_id ?? "", "invoice_note");
  const currency = useCurrency(r?.company_id);
  useEffect(() => { if (r) { setMemo(r.memo ?? ""); setDays(r.due_days === null ? "" : String(r.due_days)); } }, [r?.id, r?.memo, r?.due_days]); // eslint-disable-line react-hooks/exhaustive-deps

  const path = { batch_id: reviewId };
  const change = useMutation({
    mutationFn: (body: { group_by?: (typeof GROUPINGS)[number]; round_minutes?: (typeof ROUNDINGS)[number]; memo?: string | null; due_days?: number | null }) =>
      unwrap(api.PATCH("/api/v1/timebilling/invoice-reviews/{batch_id}", { params: { path }, body })),
    onSuccess: () => { setRegroup(null); void refresh(); },
  });
  const removeLine = useMutation({
    mutationFn: (line: ReviewLine) => unwrap(api.DELETE("/api/v1/timebilling/invoice-reviews/{batch_id}/lines/{line_id}", { params: { path: { ...path, line_id: line.id } } })),
    onSuccess: () => { setRemoving(null); toast(t("review.lineRemoved"), "ok"); void refresh(); },
  });
  const issue = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/timebilling/invoice-reviews/{batch_id}/issue", { params: { path } })),
    onSuccess: (done) => { setIssuing(false); toast(t("review.issuedOk", { number: done.invoice_number ?? "" }), "ok"); void refresh(); },
    onError: (e) => { setIssuing(false); setCreditProblem(/credit/i.test((e as Error).message)); },
  });
  const discard = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/timebilling/invoice-reviews/{batch_id}/discard", { params: { path } })),
    onSuccess: () => { toast(t("review.discardedOk"), "ok"); void refresh(); navigate("/time/unbilled"); },
  });

  if (review.isLoading) return <Skeleton className="h-64 w-full" />;
  if (review.error || !r) return <ErrorState message={review.error?.message} onRetry={() => void review.refetch()} />;
  const draft = r.status === "draft";
  const blocked = r.problems.length > 0 || r.lines.length === 0;

  return (
    <>
      <PageHeader back={{ to: "/time/unbilled", label: t("unbilled.title") }} title={t("review.title", { client: r.client_name })}
        description={<Badge tone={draft ? "warn" : r.status === "issued" ? "ok" : "neutral"}>{t(`reviews.status.${r.status}`, r.status)}</Badge>}
        actions={draft && <>
          <Button variant="ghost" onClick={() => setDiscarding(true)}>{t("review.discard")}</Button>
          <Button disabled={blocked} onClick={() => setIssuing(true)}>{t("review.issue")}</Button>
        </>} />
      <div className="space-y-4">
        {r.status === "issued" && (
          <Alert tone="ok"><strong>{t("review.issuedTitle", { number: r.invoice_number ?? "" })}</strong> {t("review.issuedBody")}{r.invoice_id && <> <Link className="font-medium underline" to={invoiceHref(r.invoice_id)}>{t("review.openInvoice")}</Link></>}</Alert>
        )}
        {draft && <Alert tone="info">{t("review.draftNote")}</Alert>}
        {draft && creditProblem && <Alert tone="warn">{t("review.creditHelp")} <Link className="font-medium underline" to={customerPath(r.client_id)}>{t("review.openClient")}</Link></Alert>}
        {draft && r.problems.length > 0 && (
          <Alert tone="bad">
            <p className="font-medium">{t("review.problems")}</p>
            <ul className="mt-1 list-disc pl-5">{r.problem_items.map((p) => <li key={`${p.code}-${p.line_no ?? ""}`}>{t(`review.problem.${p.code}`, { line: p.line_no ?? "", defaultValue: r.problems.join("; ") })}</li>)}</ul>
          </Alert>
        )}
        <Card title={t("review.lines")} flush actions={draft && <Button size="sm" variant="secondary" onClick={() => setAdding(true)}><Plus className="h-4 w-4" />{t("review.addLine")}</Button>}>
          <ReviewLines review={r} currency={currency} editable={draft} onRemove={setRemoving} />
          <div className="space-y-1 border-t border-line px-4 py-3 text-sm">
            {Number(r.write_down) > 0 && <p className="flex justify-between"><span className="text-muted">{t("review.writtenDownTotal")}</span><span className="tnum text-warn">−{money(r.write_down, currency)}</span></p>}
            <p className="flex justify-between"><span className="text-muted">{t("review.net")}</span><span className="tnum font-medium">{money(r.net_total, currency)}</span></p>
            <p className="flex justify-between"><span className="text-muted">{r.status === "issued" ? t("review.tax") : t("review.estimatedTax")}</span><span className="tnum">{money(r.status === "issued" && r.tax_total ? r.tax_total : r.estimated_tax, currency)}</span></p>
            {r.status === "issued" && r.total && <p className="flex justify-between border-t border-line pt-1 text-base font-semibold"><span>{t("review.total")}</span><span className="tnum">{money(r.total, currency)}</span></p>}
            {draft && <p className="text-xs text-muted">{t("review.taxNote")}</p>}
          </div>
        </Card>
        <PartnerReviewCard review={r} />
        <NarrativeCard review={r} editable={draft} />
        <Card title={t("review.settings")}>
          {draft ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t("review.groupBy")} hint={t("review.groupHint")}>
                <Select value={r.group_by} onChange={(e) => setRegroup({ group_by: e.target.value as (typeof GROUPINGS)[number] })}>{GROUPINGS.map((g) => <option key={g} value={g}>{t(`grouping.${g}`)}</option>)}</Select>
              </Field>
              <Field label={t("review.rounding")} hint={t("review.roundingHint")}>
                <Select value={String(r.round_minutes)} onChange={(e) => setRegroup({ round_minutes: Number(e.target.value) as (typeof ROUNDINGS)[number] })}>
                  {ROUNDINGS.map((m) => <option key={m} value={m}>{m === 0 ? t("review.noRounding") : t("review.roundTo", { minutes: m })}</option>)}
                </Select>
              </Field>
              <Field label={t("review.payDays")} hint={t("review.payDaysHint")}>
                <NumberInput value={days} onChange={(v) => setDays(v.replace(/\./g, ""))} onBlur={() => { if (days !== (r.due_days === null ? "" : String(r.due_days))) change.mutate({ due_days: days === "" ? null : Number(days) }); }} placeholder="30" />
              </Field>
              <Field label={t("review.memo")} hint={t("review.memoHint")}>
                <div className="space-y-2">
                  <Textarea value={memo} maxLength={500} onChange={(e) => setMemo(e.target.value)} onBlur={() => { if (memo !== (r.memo ?? "")) change.mutate({ memo: memo.trim() || null }); }} />
                  {!!snippets.data?.length && (
                    <Select aria-label={t("review.insertWording")} value="" onChange={(e) => { const found = snippets.data?.find((x) => x.id === e.target.value); if (found) { const next = `${memo.trim()}${memo.trim() ? " " : ""}${found.body}`.slice(0, 500); setMemo(next); change.mutate({ memo: next }); } }}>
                      <option value="">{t("review.insertWording")}</option>
                      {snippets.data.map((x) => <option key={x.id} value={x.id}>{x.name} ({x.language})</option>)}
                    </Select>
                  )}
                </div>
              </Field>
            </div>
          ) : (
            <DetailList items={[
              { label: t("review.groupBy"), value: t(`grouping.${r.group_by}`) },
              { label: t("review.rounding"), value: r.round_minutes === 0 ? t("review.noRounding") : t("review.roundTo", { minutes: r.round_minutes }) },
              { label: t("review.payDays"), value: r.due_days === null ? "—" : t("clients.days", { count: r.due_days }) },
              { label: t("review.memo"), value: r.memo || "—" },
            ]} />
          )}
        </Card>
      </div>
      <ManualLineDialog review={r} open={adding} onClose={() => setAdding(false)} />
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} onConfirm={() => removing && removeLine.mutate(removing)} busy={removeLine.isPending} danger
        title={t("review.removeLine")} message={t("review.removeAsk")} confirmLabel={t("review.removeLine")} />
      <ConfirmDialog open={!!regroup} onClose={() => setRegroup(null)} onConfirm={() => regroup && change.mutate(regroup)} busy={change.isPending}
        title={t("review.rebuildTitle")} message={t("review.rebuildAsk")} confirmLabel={t("review.rebuild")} />
      <ConfirmDialog open={issuing} onClose={() => setIssuing(false)} onConfirm={() => issue.mutate()} busy={issue.isPending}
        title={t("review.issue")} message={t("review.issueAsk", { client: r.client_name, amount: money(r.net_total, currency) })} confirmLabel={t("review.issue")} />
      <ConfirmDialog open={discarding} onClose={() => setDiscarding(false)} onConfirm={() => discard.mutate()} busy={discard.isPending} danger
        title={t("review.discard")} message={t("review.discardAsk")} confirmLabel={t("review.discard")} />
    </>
  );
}
