import { useState } from "react";

import { api, Badge, Button, DataTable, Drawer, ErrorState, humanise, money, Skeleton, unwrap, useQuery, useTranslation } from "@/sdk";

import type { ReturnDetail, ReturnSummary, Run } from "../lib/types";
import { DownloadButton } from "./DownloadButton";

/** What the run owes under each statutory rule, with a list per employee and a CSV to adapt to the form the authority asks for. */
export function ReturnsPanel({ run, currency }: { run: Run; currency?: string }) {
  const { t } = useTranslation("people");
  const [open, setOpen] = useState<ReturnSummary | null>(null);
  const returns = useQuery({ queryKey: ["people", "run", run.id, "returns", run.status], queryFn: () => unwrap(api.GET("/api/v1/people/payroll-runs/{run_id}/returns", { params: { path: { run_id: run.id } } })) });
  return (
    <>
      <DataTable
        rows={returns.data} loading={returns.isLoading} error={returns.error?.message} onRetry={() => void returns.refetch()} rowKey={(r) => r.code}
        empty={{ title: t("returns.empty"), hint: t("returns.emptyHint") }}
        columns={[
          { header: t("rules.name"), cell: (r) => <span className="font-medium">{r.name}<span className="ml-2 font-mono text-xs font-normal text-muted">{r.code}</span></span> },
          { header: t("rules.kind"), hideBelow: "sm", cell: (r) => <Badge>{t(`rules.kinds.${r.kind}`, humanise(r.kind))}</Badge> },
          { header: t("returns.employee"), align: "right", cell: (r) => money(r.employee, currency) },
          { header: t("returns.employer"), align: "right", cell: (r) => money(r.employer, currency) },
          {
            header: "", align: "right", cell: (r) => (
              <span className="flex justify-end gap-1.5">
                <Button size="sm" variant="secondary" onClick={() => setOpen(r)}>{t("returns.view")}</Button>
                <DownloadButton size="sm" fileName={`return-${r.code}-${run.period_start}.csv`}
                  request={() => api.GET("/api/v1/people/payroll-runs/{run_id}/returns/{code}", { params: { path: { run_id: run.id, code: r.code }, query: { format: "csv" } }, parseAs: "blob" })}>{t("csv")}</DownloadButton>
              </span>
            ),
          },
        ]}
      />
      <ReturnDrawer run={run} summary={open} onClose={() => setOpen(null)} currency={currency} />
    </>
  );
}

function ReturnDrawer({ run, summary, onClose, currency }: { run: Run; summary: ReturnSummary | null; onClose: () => void; currency?: string }) {
  const { t } = useTranslation("people");
  const code = summary?.code ?? "";
  const detail = useQuery({
    enabled: !!summary, queryKey: ["people", "run", run.id, "return", code],
    queryFn: async () => (await unwrap(api.GET("/api/v1/people/payroll-runs/{run_id}/returns/{code}", { params: { path: { run_id: run.id, code } } }))) as ReturnDetail,
  });
  return (
    <Drawer open={!!summary} onClose={onClose} title={summary ? `${summary.name} · ${run.period_start} → ${run.period_end}` : ""}
      footer={summary && <DownloadButton fileName={`return-${code}-${run.period_start}.csv`}
        request={() => api.GET("/api/v1/people/payroll-runs/{run_id}/returns/{code}", { params: { path: { run_id: run.id, code }, query: { format: "csv" } }, parseAs: "blob" })}>{t("csv")}</DownloadButton>}>
      {detail.error ? <ErrorState message={detail.error.message} onRetry={() => void detail.refetch()} /> : !detail.data ? <Skeleton className="h-40" /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="rounded-lg bg-sunken p-3"><p className="text-xs text-muted">{t("returns.employee")}</p><p className="tnum text-lg font-semibold">{money(detail.data.employee_total, currency)}</p></div>
            <div className="rounded-lg bg-sunken p-3"><p className="text-xs text-muted">{t("returns.employer")}</p><p className="tnum text-lg font-semibold">{money(detail.data.employer_total, currency)}</p></div>
          </div>
          <ul className="divide-y divide-line rounded-xl border border-line">
            {detail.data.rows.map((r) => (
              <li key={r.employee_no} className="px-3 py-2.5 text-sm">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-medium">{r.name} <span className="font-mono text-xs font-normal text-muted">{r.employee_no}</span></span>
                  <span className="tnum">{money(r.employee_amount, currency)}</span>
                </div>
                <p className="mt-0.5 text-xs text-muted">
                  {t("returns.chargedOn", { base: money(r.base, currency) })} · {t("returns.employer")}: {money(r.employer_amount, currency)}
                  {r.tax_id && <> · {t("employee.taxId")}: {r.tax_id}</>}{r.registration_no && <> · {t("returns.registration")}: {r.registration_no}</>}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Drawer>
  );
}
