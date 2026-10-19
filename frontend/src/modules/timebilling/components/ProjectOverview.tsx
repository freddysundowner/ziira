import { Alert, api, Attachments, Badge, Card, CustomFields, DetailList, useCan, ErrorState, formatDate, money, percent, Skeleton, Stat, unwrap, useQuery, useTranslation } from "@/sdk";

import { useStaff } from "../hooks";
import { barWidth, formatDuration } from "../lib";
import type { Project } from "../types";

function Progress({ label, value, detail, state }: { label: string; value: string | null; detail: string; state: string }) {
  const tone = state === "over" ? "bg-bad" : state === "near" ? "bg-warn" : "bg-brand";
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2 text-sm"><span className="font-medium">{label}</span><span className="tnum text-muted">{detail}</span></div>
      <div className="h-2.5 overflow-hidden rounded-full bg-sunken" role="img" aria-label={`${label}: ${value === null ? "—" : percent(value, 0)}`}>
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${barWidth(value)}%` }} />
      </div>
    </div>
  );
}

/** How the project stands: time logged against its budget, what is billed and what is waiting to be billed. */
export function ProjectOverview({ project, currency }: { project: Project; currency?: string }) {
  const { t } = useTranslation("timebilling");
  const staff = useStaff(project.company_id);
  const canManage = useCan("projects.manage");
  const summary = useQuery({
    queryKey: ["timebilling", "project-summary", project.id],
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/projects/{project_id}/summary", { params: { path: { project_id: project.id } } })),
  });
  if (summary.isLoading) return <Skeleton className="h-48 w-full" />;
  if (summary.error) return <ErrorState message={summary.error.message} onRetry={() => void summary.refetch()} />;
  const s = summary.data!;
  const manager = staff.data?.find((x) => x.user_id === project.manager_id)?.name;

  return (
    <div className="space-y-4">
      {s.budget_state === "over" && <Alert tone="bad">{t("summary.over")}</Alert>}
      {s.budget_state === "near" && <Alert tone="warn">{t("summary.near")}</Alert>}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={t("summary.logged")} value={formatDuration(s.logged_minutes)} hint={t("summary.billableOf", { time: formatDuration(s.billable_minutes) })} />
        <Stat label={t("summary.waitingApproval")} value={formatDuration(s.unapproved_minutes)} hint={t("summary.waitingApprovalHint")} />
        <Stat label={t("summary.unbilled")} value={money(s.unbilled_amount, currency)} hint={t("summary.unbilledHint")} />
        <Stat label={t("summary.billed")} value={money(s.billed_amount, currency)} />
      </div>
      {s.fee_cap_percent !== null && project.fee_cap && (
        <Card title={t("summary.feeCap")}>
          <Progress label={t("summary.capUsed")} value={s.fee_cap_percent ?? null} state={s.budget_state}
            detail={`${money(project.fee_cap, currency)} · ${percent(s.fee_cap_percent, 0)}`} />
          {Number(s.over_cap_amount) > 0 && <p className="mt-3 text-sm text-bad">{t("summary.overCap", { amount: money(s.over_cap_amount, currency) })}</p>}
          <p className="mt-2 text-xs text-muted">{t("summary.capHint")}</p>
        </Card>
      )}
      {(s.budget_minutes_percent !== null || s.budget_amount_percent !== null) && (
        <Card title={t("summary.budget")}>
          <div className="space-y-4">
            {s.budget_minutes_percent !== null && project.budget_minutes && (
              <Progress label={t("summary.hoursBudget")} value={s.budget_minutes_percent} state={s.budget_state}
                detail={`${formatDuration(s.logged_minutes)} / ${formatDuration(project.budget_minutes)} · ${percent(s.budget_minutes_percent, 0)}`} />
            )}
            {s.budget_amount_percent !== null && project.budget_amount && (
              <Progress label={t("summary.amountBudget")} value={s.budget_amount_percent} state={s.budget_state}
                detail={`${money(s.billed_amount, currency)} + ${money(s.unbilled_amount, currency)} / ${money(project.budget_amount, currency)} · ${percent(s.budget_amount_percent, 0)}`} />
            )}
          </div>
        </Card>
      )}
      {s.cost !== null && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat label={t("summary.cost")} value={money(s.cost, currency)} hint={s.unpriced_cost_minutes > 0 ? t("summary.unpricedCost", { time: formatDuration(s.unpriced_cost_minutes) }) : undefined} />
          <Stat label={t("summary.margin")} value={s.margin === null ? "—" : money(s.margin, currency)} tone={s.margin !== null && Number(s.margin) < 0 ? "bad" : undefined} />
          <Stat label={t("summary.marginPercent")} value={s.margin_percent === null ? "—" : percent(s.margin_percent, 0)} tone={s.margin_percent !== null && Number(s.margin_percent) < 0 ? "bad" : undefined} />
        </div>
      )}
      <Card title={t("summary.details")}>
        <DetailList items={[
          { label: t("client"), value: project.client_name },
          { label: t("projects.billingMode"), value: <Badge>{t(`projects.mode.${project.billing_mode}`)}</Badge> },
          ...(project.fixed_fee ? [{ label: t("projects.fixedFee"), value: money(project.fixed_fee, currency) }] : []),
          ...(project.fee_cap ? [{ label: t("projects.feeCap"), value: money(project.fee_cap, currency) }] : []),
          { label: t("projects.manager"), value: manager ?? "—" },
          { label: t("projects.starts"), value: formatDate(project.starts_on) },
          { label: t("projects.ends"), value: formatDate(project.ends_on) },
          { label: t("note"), value: project.notes || "—" },
        ]} />
      </Card>
      <CustomFields entityType="timebilling.project" entityId={project.id} canEdit={canManage} />
      <Attachments entityType="timebilling.project" entityId={project.id} title={t("project.documents")} />
    </div>
  );
}
