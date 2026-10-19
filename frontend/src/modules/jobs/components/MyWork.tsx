import { Link } from "react-router-dom";

import { api, Badge, Card, EmptyState, ErrorState, formatDate, Skeleton, unwrap, useQuery, useSession, useTranslation } from "@/sdk";

import { jobHref } from "../public";
import type { JobSummary } from "../types";
import { StageBadge } from "./StageBadge";

/** A technician's day: the jobs they are in charge of, late first, then what waits on parts, approval or the insurer. */
export function MyWork({ companyId }: { companyId: string }) {
  const { t } = useTranslation("jobs");
  const me = useSession().me?.user_id ?? "";
  const mine = useQuery({
    queryKey: ["jobs", "my-work", companyId, me], enabled: !!companyId && !!me,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/jobs", { params: { query: { company_id: companyId, assignee_id: me, open_only: true, limit: 100 } } })),
  });
  if (mine.error) return <ErrorState title={t("garage.work.loadFailed")} message={mine.error.message} onRetry={() => void mine.refetch()} />;
  if (!mine.data) return <Skeleton className="h-48" />;
  const today = new Date().toISOString().slice(0, 10);
  const late = mine.data.filter((j) => j.overdue);
  const waiting = mine.data.filter((j) => !j.overdue && j.waiting_on.length > 0);
  const dueToday = mine.data.filter((j) => !j.overdue && j.waiting_on.length === 0 && j.promised_at === today);
  const rest = mine.data.filter((j) => !late.includes(j) && !waiting.includes(j) && !dueToday.includes(j));
  if (mine.data.length === 0) return <EmptyState title={t("garage.work.empty")} hint={t("garage.work.emptyHint")} />;
  return (
    <div className="space-y-4">
      <Section title={t("garage.work.late")} jobs={late} tone="bad" />
      <Section title={t("garage.work.today")} jobs={dueToday} />
      <Section title={t("garage.work.waiting")} jobs={waiting} tone="warn" />
      <Section title={t("garage.work.rest")} jobs={rest} />
    </div>
  );
}

function Section({ title, jobs, tone }: { title: string; jobs: JobSummary[]; tone?: "bad" | "warn" }) {
  const { t } = useTranslation("jobs");
  if (jobs.length === 0) return null;
  return (
    <Card title={<span className="inline-flex items-center gap-2">{title}<Badge tone={tone ?? "neutral"}>{jobs.length}</Badge></span>} flush>
      <ul className="divide-y divide-line">
        {jobs.map((j) => (
          <li key={j.id}>
            <Link to={jobHref(j.id)} className="flex min-h-14 flex-wrap items-center justify-between gap-2 px-4 py-3 hover:bg-sunken/60">
              <span className="min-w-0">
                <span className="tnum text-xs font-medium text-muted">{j.number}</span>
                <span className="block truncate text-sm font-medium">{j.title}</span>
                <span className="block truncate text-xs text-muted">{[j.asset?.label, j.customer_name].filter(Boolean).join(" · ")}</span>
              </span>
              <span className="flex flex-wrap items-center gap-1.5 text-xs">
                <StageBadge stage={j.status} />
                {j.waiting_on.map((w) => <Badge key={w} tone="warn">{t(`garage.waiting.${w}`)}</Badge>)}
                {j.promised_at && <span className={j.overdue ? "font-medium text-bad" : "text-muted"}>{formatDate(j.promised_at)}</span>}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}
