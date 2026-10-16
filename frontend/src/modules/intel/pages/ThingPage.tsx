import { useState } from "react";
import { useParams } from "react-router-dom";

import { api, Button, Card, ErrorState, PageHeader, Skeleton, Switch, unwrap, useCan, useQuery, useSession, useTranslation } from "@/sdk";

import AiExplanation from "../components/AiExplanation";
import { FindingStatusBadge, SeverityBadge } from "../components/Badges";
import FindingDialog, { type DialogKind } from "../components/FindingDialogs";
import Glossary from "../components/Glossary";
import NotAProblemDialog from "../components/NotAProblemDialog";
import SnoozeMenu from "../components/SnoozeMenu";
import SuggestedActions from "../components/SuggestedActions";
import Timeline from "../components/Timeline";
import { actionsFor } from "../logic";
import FactsCard from "../thing/FactsCard";
import RelatedCard from "../thing/RelatedCard";
import TechnicalDetails from "../thing/TechnicalDetails";
import { useNames } from "../useNames";
import { usePlain } from "../usePlain";
import { useTechnical } from "../useTechnical";

/** One thing to look at: what it is, why it matters, what to do next, the facts, who has it, and what happened so far. */
export default function ThingPage() {
  const { t } = useTranslation("intel");
  const { findingId = "" } = useParams();
  const { me } = useSession();
  const plain = usePlain();
  const { branchName } = useNames();
  const canManage = useCan("findings.manage");
  const canRespond = useCan("findings.respond");
  const [dialog, setDialog] = useState<DialogKind | null>(null);
  const [ignoring, setIgnoring] = useState(false);
  const [technical, setTechnical] = useTechnical();
  const q = useQuery({
    queryKey: ["intel", "finding", findingId],
    queryFn: () => unwrap(api.GET("/api/v1/intel/findings/{finding_id}", { params: { path: { finding_id: findingId } } })),
  });
  const f = q.data;
  const back = { to: "/intelligence/things", label: t("things.title") };

  if (q.error) return <><PageHeader title={t("thing.title")} back={back} /><ErrorState message={q.error.message} onRetry={() => void q.refetch()} /></>;
  if (!f) return <><PageHeader title={t("thing.title")} back={back} /><Skeleton className="h-64 w-full" /></>;

  const can = actionsFor(f, { manage: canManage, respond: canRespond }, me?.user_id ?? null);
  const text = plain.check(f.check_code);
  const where = branchName(f.branch_id);
  const snoozed = f.snoozed_until && new Date(f.snoozed_until) > new Date();

  return (
    <>
      <PageHeader back={back} title={text?.title ?? f.summary ?? t("noSummary")}
        description={<span className="inline-flex flex-wrap items-center gap-2"><SeverityBadge severity={f.severity} /><FindingStatusBadge status={f.status} />{text && <span>{plain.topicTitle(text.topic)}</span>}{where && <span>· {where}</span>}</span>}
        actions={
          <>
            {can.acknowledge && <Button variant="secondary" onClick={() => setDialog("acknowledge")}>{t("action.acknowledge")}</Button>}
            {can.explain && <Button onClick={() => setDialog("explain")}>{t("action.explain")}</Button>}
            {can.resolve && <Button variant="secondary" onClick={() => setDialog("resolve")}>{t("action.resolve")}</Button>}
            {can.assign && <Button variant="secondary" onClick={() => setDialog("assign")}>{t("action.assign")}</Button>}
            {can.ask && <Button variant="secondary" onClick={() => setDialog("ask")}>{t("action.ask")}</Button>}
            {can.snooze && <SnoozeMenu findingId={f.id} />}
            {can.dismiss && <Button variant="ghost" onClick={() => setIgnoring(true)}>{t("action.dismiss")}</Button>}
          </>
        } />
      {snoozed && <p className="mb-3 rounded-lg bg-sunken px-3 py-2 text-sm text-muted">{t("thing.snoozed", { date: new Date(f.snoozed_until!).toLocaleDateString() })}</p>}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title={t("thing.noticed")}><p className="text-sm">{f.summary ?? t("noSummary")}</p></Card>
          {text?.why && <Card title={t("thing.why")}><p className="text-sm">{text.why}</p></Card>}
          {(text?.todo || f.recommended_action) && (
            <Card title={t("thing.next")}>
              <div className="space-y-2 text-sm">
                {text?.todo && <p>{text.todo}</p>}
                {f.recommended_action && <p className="text-muted">{f.recommended_action}</p>}
              </div>
            </Card>
          )}
          {f.explanation && <Card title={t("explanation")} description={t("explanationHint")}><p className="whitespace-pre-wrap text-sm">{f.explanation}</p></Card>}
          <AiExplanation finding={f} />
          <SuggestedActions findingId={f.id} companyId={f.company_id ?? undefined} />
          <Card title={t("timeline")}><Timeline events={f.events} /></Card>
        </div>
        <div className="space-y-4">
          <FactsCard finding={f} />
          <RelatedCard findingId={f.id} />
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="inline-flex items-center gap-2 text-sm"><Switch label={t("tech.show")} checked={technical} onChange={setTechnical} />{t("tech.show")}</span>
              <Glossary terms={["yourNormal", "urgentSoon", "notAProblem"]} />
            </div>
          </Card>
        </div>
      </div>
      {technical && <div className="mt-4"><TechnicalDetails finding={f} /></div>}
      <FindingDialog kind={dialog} finding={f} onClose={() => setDialog(null)} />
      <NotAProblemDialog findingId={f.id} open={ignoring} onClose={() => setIgnoring(false)} />
    </>
  );
}
