import { Link } from "react-router-dom";

import { api, Badge, DataTable, formatDate, unwrap, useQuery, useTranslation } from "@/sdk";

import { jobHref } from "../public";

/** Courtesy and hire cars that are out on loan now. */
export function CarsOut({ companyId }: { companyId: string }) {
  const { t } = useTranslation("jobs");
  const rows = useQuery({
    queryKey: ["jobs", "cars-out", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/loans/out", { params: { query: { company_id: companyId } } })),
  });
  return (
    <DataTable rows={rows.data} loading={rows.isLoading} error={rows.error?.message} onRetry={() => void rows.refetch()}
      rowKey={(r) => r.id} rowHref={(r) => jobHref(r.job_id)} empty={{ title: t("garage.cars.empty"), hint: t("garage.cars.emptyHint") }}
      columns={[
        { header: t("garage.cars.car"), cell: (r) => <span className="font-medium">{r.asset_label}</span> },
        { header: t("garage.cars.job"), cell: (r) => <Link className="tnum text-brand-strong hover:underline" to={jobHref(r.job_id)} onClick={(e) => e.stopPropagation()}>{r.job_number}</Link> },
        { header: t("garage.cars.with"), cell: (r) => r.borrower_name ?? "—", hideBelow: "sm" },
        { header: t("garage.cars.out"), cell: (r) => formatDate(r.out_at, true), hideBelow: "md" },
        { header: t("garage.cars.due"), cell: (r) => <span className="inline-flex items-center gap-2">{r.due_at ? formatDate(r.due_at) : "—"}{r.overdue && <Badge tone="warn">{t("garage.loan.overdue")}</Badge>}</span> },
      ]} />
  );
}
