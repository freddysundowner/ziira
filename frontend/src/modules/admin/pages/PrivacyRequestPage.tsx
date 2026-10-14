import { useState } from "react";
import { useParams } from "react-router-dom";

import {
  api, Alert, Badge, Card, DetailList, ErrorState, formatDate, SkeletonRows, StatusBadge, PageHeader, today, unwrap, useCan, useCompany, useQuery,
  useTranslation,
} from "@/sdk";

import CloseStep from "./privacy/CloseStep";
import EraseStep from "./privacy/EraseStep";
import ExportStep from "./privacy/ExportStep";
import { dueState, hasSearched, isFinished, recordIdsFor, selectedRecords } from "./privacy/model";
import SearchStep from "./privacy/SearchStep";
import StepCard, { type StepState } from "./privacy/StepCard";
import { useUserNames } from "./privacy/useUserNames";

/** One data subject request, handled in steps: search, export, erase (erasure only), close. */
export default function PrivacyRequestPage() {
  const { requestId = "" } = useParams();
  const { t } = useTranslation("kernel");
  const canManage = useCan("privacy.manage");
  const { companies } = useCompany();
  const userName = useUserNames();
  const [confirmed, setConfirmed] = useState<ReadonlySet<string>>(new Set());
  const query = useQuery({ queryKey: ["privacy-request", requestId], queryFn: () => unwrap(api.GET("/api/v1/privacy/requests/{request_id}", { params: { path: { request_id: requestId } } })) });

  const back = { to: "/admin/privacy", label: t("dsr.backToList") };
  if (query.error) return <><PageHeader title={t("privacy")} back={back} /><ErrorState message={query.error.message} onRetry={() => void query.refetch()} /></>;
  const request = query.data;
  if (!request) return <><PageHeader title={t("privacy")} back={back} /><SkeletonRows rows={6} cols={2} /></>;

  const toggle = (id: string, on: boolean) => setConfirmed((prev) => { const next = new Set(prev); if (on) next.add(id); else next.delete(id); return next; });
  const finished = isFinished(request);
  const searched = hasSearched(request);
  const erasure = request.request_type === "erasure";
  const selected = selectedRecords(request.found, confirmed);
  const due = dueState(request, today());
  const stateOf = (done: boolean, needsSearch = true): StepState => (finished ? "done" : needsSearch && !searched ? "locked" : done ? "done" : "current");
  const company = companies.find((c) => c.id === request.company_id)?.name;
  let step = 0;

  return (
    <>
      <PageHeader back={back} title={request.number} description={t(`dsr.typeName.${request.request_type}`)} actions={<StatusBadge status={request.status} />} />
      <div className="space-y-4">
        {request.awaiting_approval && !finished && <Alert tone="warn">{t("dsr.erase.waiting")}</Alert>}
        <Card>
          <DetailList items={[
            { label: t("dsr.subject"), value: request.subject_masked },
            { label: t("company"), value: company ?? "—" },
            { label: t("dsr.receivedOn"), value: formatDate(request.received_on) },
            { label: t("dsr.due"), value: <span className={due === "overdue" ? "font-medium text-bad" : undefined}>{formatDate(request.due_date)}{due === "overdue" && <Badge tone="bad" className="ml-2">{t("dsr.overdue")}</Badge>}{due === "soon" && <Badge tone="warn" className="ml-2">{t("dsr.dueSoon")}</Badge>}</span> },
            { label: t("dsr.handler"), value: userName(request.handled_by) },
            { label: t("dsr.notes"), value: request.notes ? <span className="whitespace-pre-wrap">{request.notes}</span> : "—" },
          ]} />
        </Card>

        <StepCard number={++step} title={t("dsr.step.search")} hint={t("dsr.step.searchHint")} state={finished ? "done" : searched ? "done" : "current"}>
          <SearchStep request={request} confirmed={confirmed} onToggle={toggle} canEdit={canManage} />
        </StepCard>
        <StepCard number={++step} title={t("dsr.step.export")} hint={t("dsr.step.exportHint")} state={stateOf(request.outcome?.exports !== undefined)}>
          <ExportStep request={request} recordIds={recordIdsFor(request.found, confirmed)} count={selected.length} canEdit={canManage} />
        </StepCard>
        {erasure && (
          <StepCard number={++step} title={t("dsr.step.erase")} hint={t("dsr.step.eraseHint")} state={stateOf(request.outcome?.erasure !== undefined)}>
            <EraseStep request={request} found={request.found} confirmed={confirmed} userName={userName} canEdit={canManage} />
          </StepCard>
        )}
        <StepCard number={++step} title={t("dsr.step.close")} hint={t("dsr.step.closeHint")} state={finished ? "done" : searched ? "current" : "locked"}>
          <CloseStep request={request} canEdit={canManage} />
        </StepCard>
      </div>
    </>
  );
}
