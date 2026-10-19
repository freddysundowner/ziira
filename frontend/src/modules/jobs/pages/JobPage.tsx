import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ClaimPanel } from "@/modules/claims/public";
import { customerPath } from "@/modules/crm/public";
import { Alert, api, Badge, Button, ErrorState, formatDate, PageHeader, Skeleton, Tabs, unwrap, useCan, useTranslation } from "@/sdk";

import { ClaimWork } from "../components/ClaimWork";
import { EstimatesTab } from "../components/EstimatesTab";
import { JobAlerts } from "../components/JobAlerts";
import { JobActions } from "../components/JobActions";
import { OverviewTab } from "../components/OverviewTab";
import { PartsTab } from "../components/PartsTab";
import { PhotosTab } from "../components/PhotosTab";
import { StageBadge } from "../components/StageBadge";
import { SummaryCard } from "../components/SummaryCard";
import { TimelineTab } from "../components/TimelineTab";
import { WorkshopTab } from "../components/WorkshopTab";
import { useJob, useJobAction, useJobsCompany, useUnit, useWorkflow } from "../hooks";
import { assetHref } from "../public";
import type { Job } from "../types";

type Tab = "overview" | "parts" | "estimates" | "photos" | "workshop" | "timeline";

/** One work order: where it is, what is wrong, what was used, the estimates and the story so far. */
export default function JobPage() {
  const { t } = useTranslation("jobs");
  const { jobId = "" } = useParams();
  const job = useJob(jobId);
  const { currency } = useJobsCompany();
  const workflow = useWorkflow(job.data?.company_id ?? "");
  const canManage = useCan("jobs.manage");
  const hasClaims = useUnit("claims");
  const [tab, setTab] = useState<Tab>("overview");

  if (job.error) return <ErrorState title={t("job.loadFailed")} message={job.error.message} onRetry={() => void job.refetch()} />;
  if (!job.data || !workflow.data) return <Skeleton className="h-96" />;
  const j = job.data;
  const editable = canManage && !j.locked;
  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "overview", label: t("job.tabs.overview") },
    { id: "parts", label: t("job.tabs.parts"), count: j.parts.filter((p) => !p.voided).length + j.labour.filter((l) => !l.voided).length || undefined },
    { id: "estimates", label: t("job.tabs.estimates"), count: j.estimates.length || undefined },
    { id: "photos", label: t("job.tabs.photos"), count: j.photo_count || undefined },
    { id: "workshop", label: t("job.tabs.workshop") },
    { id: "timeline", label: t("job.tabs.timeline") },
  ];
  return (
    <>
      <PageHeader title={`${j.number} · ${j.title}`} back={{ to: "/jobs", label: t("menu.jobs") }} description={<Meta job={j} />} />
      <div className="mb-5"><JobActions job={j} workflow={workflow.data} currency={currency} /></div>
      {j.locked && <Alert tone="info" className="mb-4">{j.invoiced ? t("job.lockedInvoiced", { number: j.invoice_number ?? "" }) : t("job.lockedClosed")}</Alert>}
      <JobAlerts job={j} currency={currency} onTab={setTab} />
      <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0">
          <Tabs tabs={tabs} value={tab} onChange={setTab} />
          {tab === "overview" && <OverviewTab job={j} editable={editable} />}
          {tab === "parts" && <PartsTab job={j} currency={currency} editable={editable} />}
          {tab === "estimates" && <EstimatesTab job={j} currency={currency} editable={editable} />}
          {tab === "photos" && <PhotosTab job={j} />}
          {tab === "workshop" && <WorkshopTab job={j} currency={currency} editable={editable} />}
          {tab === "timeline" && <TimelineTab job={j} />}
        </div>
        <aside className="space-y-4">
          {hasClaims && !j.customer_id && !j.claim && !j.locked && <NeedCustomerRecord job={j} />}
          {hasClaims && <ClaimPanel sourceType="job" sourceId={j.id} companyId={j.company_id} branchId={j.branch_id} customerId={j.customer_id} subject={j.asset?.label ?? j.title} />}
          <ClaimWork job={j} currency={currency} />
          <SummaryCard job={j} currency={currency} />
        </aside>
      </div>
    </>
  );
}

/** An insurer claim bills the customer's excess to a customer record: make one for a walk-in first. */
function NeedCustomerRecord({ job }: { job: Job }) {
  const { t } = useTranslation("jobs");
  const make = useJobAction(job.id, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/customer-record", { params: { path: { job_id: job.id } } })), { done: t("garage.claim.recordMade") });
  return (
    <Alert tone="info">
      <span className="block text-sm">{t("garage.claim.needRecord")}</span>
      <Button size="sm" className="mt-2" variant="secondary" loading={make.isPending} onClick={() => make.mutate(undefined)}>{t("garage.claim.makeRecord")}</Button>
    </Alert>
  );
}

/** The line under the title: stage, item, customer, person in charge, dates. */
function Meta({ job }: { job: Job }) {
  const { t } = useTranslation("jobs");
  const hasCustomers = useUnit("crm");
  const link = "font-medium text-brand-strong hover:underline";
  const customer = job.customer_name ?? "";
  return (
    <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <StageBadge stage={job.status} />
      {job.is_rework && <Badge tone="warn">{t("card.returnVisit")}</Badge>}
      {job.waiting_on.map((w) => <Badge key={w} tone="warn">{t(`garage.waiting.${w}`)}</Badge>)}
      {job.asset && <Link className={link} to={assetHref(job.asset.id)}>{job.asset.label}</Link>}
      {customer && (job.customer_id && hasCustomers ? <Link className={link} to={customerPath(job.customer_id)}>{customer}</Link> : <span>{customer}</span>)}
      {job.customer_phone && <a className={link} href={`tel:${job.customer_phone}`}>{job.customer_phone}</a>}
      {job.assignee_name && <span>{t("job.inCharge", { name: job.assignee_name })}</span>}
      {job.promised_at && <span className={job.overdue ? "font-medium text-bad" : undefined}>{job.overdue ? t("card.late", { date: formatDate(job.promised_at) }) : t("card.due", { date: formatDate(job.promised_at) })}</span>}
      <span>{t("job.received", { date: formatDate(job.received_at, true) })}</span>
    </span>
  );
}
