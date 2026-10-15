import { useState } from "react";
import { useParams } from "react-router-dom";

import {
  api, Badge, Button, Card, DetailList, ErrorState, formatDate, humanise, money, PageHeader, Skeleton, unwrap, useCan, useCompany, useQuery, useSession, useTranslation,
} from "@/sdk";

import { FindingStatusBadge, SeverityBadge, useAreaLabel } from "../components/Badges";
import AiExplanation from "../components/AiExplanation";
import FindingDialog, { type DialogKind } from "../components/FindingDialogs";
import SuggestedActions from "../components/SuggestedActions";
import Timeline from "../components/Timeline";
import { actionsFor, ageInDays } from "../logic";

export default function FindingPage() {
  const { t } = useTranslation("intel");
  const { findingId = "" } = useParams();
  const areaLabel = useAreaLabel();
  const { me } = useSession();
  const canManage = useCan("findings.manage");
  const canRespond = useCan("findings.respond");
  const [dialog, setDialog] = useState<DialogKind | null>(null);
  const q = useQuery({
    queryKey: ["intel", "finding", findingId],
    queryFn: () => unwrap(api.GET("/api/v1/intel/findings/{finding_id}", { params: { path: { finding_id: findingId } } })),
  });
  const f = q.data;
  const { company } = useCompany(f?.company_id ?? undefined);
  const back = { to: "/findings", label: t("title") };

  if (q.error) return <><PageHeader title={t("finding")} back={back} /><ErrorState message={q.error.message} onRetry={() => void q.refetch()} /></>;
  if (!f) return <><PageHeader title={t("finding")} back={back} /><Skeleton className="h-64 w-full" /></>;

  const can = actionsFor(f, { manage: canManage, respond: canRespond }, me?.user_id ?? null);
  const branch = company?.branches.find((b) => b.id === f.branch_id)?.name;
  const assignee = !f.owner_user_id ? null : f.owner_user_id === me?.user_id ? t("assignedYou") : t("assignedSomeone");
  const hasFigures = Object.keys(f.figures).length > 0;

  return (
    <>
      <PageHeader back={back} title={f.summary ?? t("noSummary")}
        description={<span className="inline-flex flex-wrap items-center gap-2"><SeverityBadge severity={f.severity} /><FindingStatusBadge status={f.status} /><span>{areaLabel(f.area)}</span></span>}
        actions={
          <>
            {can.acknowledge && <Button variant="secondary" onClick={() => setDialog("acknowledge")}>{t("action.acknowledge")}</Button>}
            {can.explain && <Button onClick={() => setDialog("explain")}>{t("action.explain")}</Button>}
            {can.resolve && <Button variant="secondary" onClick={() => setDialog("resolve")}>{t("action.resolve")}</Button>}
            {can.assign && <Button variant="secondary" onClick={() => setDialog("assign")}>{t("action.assign")}</Button>}
            {can.ask && <Button variant="secondary" onClick={() => setDialog("ask")}>{t("action.ask")}</Button>}
            {can.dismiss && <Button variant="ghost" onClick={() => setDialog("dismiss")}>{t("action.dismiss")}</Button>}
          </>
        } />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {f.recommended_action && <Card title={t("recommended")}><p className="text-sm">{f.recommended_action}</p></Card>}
          {f.explanation && <Card title={t("explanation")} description={t("explanationHint")}><p className="whitespace-pre-wrap text-sm">{f.explanation}</p></Card>}
          <AiExplanation finding={f} />
          <SuggestedActions findingId={f.id} companyId={f.company_id ?? undefined} />
          {(hasFigures || f.records.length > 0) && (
            <Card title={t("evidence")} description={t("evidenceHint")}>
              <div className="space-y-4">
                {hasFigures && <DetailList items={Object.entries(f.figures).map(([k, v]) => ({ label: t(`figure.${k}`, humanise(k)), value: v }))} />}
                {f.records.length > 0 && (
                  <ul className="divide-y divide-line">
                    {f.records.map((r, i) => (
                      <li key={`${r.type}-${r.id ?? i}`} className="flex flex-wrap items-center gap-2 py-2 text-sm first:pt-0 last:pb-0">
                        <Badge>{t(`record.${r.type.replace(/\./g, "_")}`, humanise(r.type.split(".").pop()))}</Badge>
                        <span>{r.label}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Card>
          )}
          <Card title={t("timeline")}><Timeline events={f.events} /></Card>
        </div>
        <Card title={t("details")}>
          <DetailList items={[
            { label: t("amount"), value: f.amount ? money(f.amount, company?.currency) : "—" },
            { label: t("found"), value: f.value ? t("valueVsExpected", { value: f.value, expected: f.expected_value ?? "—" }) : "—" },
            { label: t("branch"), value: branch ?? t("allBranches") },
            { label: t("period"), value: f.period_start ? `${formatDate(f.period_start)}${f.period_end && f.period_end !== f.period_start ? ` – ${formatDate(f.period_end)}` : ""}` : "—" },
            { label: t("firstSeen"), value: `${formatDate(f.first_seen_at, true)} (${t("days", { count: ageInDays(f.first_seen_at) })})` },
            { label: t("lastSeen"), value: formatDate(f.last_seen_at, true) },
            { label: t("assignedTo"), value: assignee ?? t("unassigned") },
            ...(f.resolved_at ? [{ label: t("closedOn"), value: formatDate(f.resolved_at, true) }] : []),
            { label: t("check"), value: <span className="font-mono text-xs">{f.check_code ?? "—"}</span> },
          ]} />
        </Card>
      </div>
      <FindingDialog kind={dialog} finding={f} onClose={() => setDialog(null)} />
    </>
  );
}
