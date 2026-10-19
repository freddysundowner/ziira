import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, Button, EmptyState, ErrorState, formatDate, Select, Skeleton, unwrap, useQuery, useTranslation } from "@/sdk";

import { useBranchChoice } from "../hooks";
import { jobHref } from "../public";

const DAYS = 7;
const iso = (d: Date): string => d.toISOString().slice(0, 10);
const addDays = (d: Date, n: number): Date => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };

/** Which job is in which bay on which day. Jobs are put in a bay from the job's Workshop tab. */
export function BayBoard({ companyId, branches }: { companyId: string; branches: readonly { id: string; name: string }[] }) {
  const { t } = useTranslation("jobs");
  const { branchId, setBranchId } = useBranchChoice(branches);
  const [start, setStart] = useState(() => new Date());
  const days = Array.from({ length: DAYS }, (_, i) => addDays(start, i));
  const board = useQuery({
    queryKey: ["jobs", "bay-board", companyId, branchId, iso(start)], enabled: !!companyId && !!branchId,
    queryFn: () => unwrap(api.GET("/api/v1/jobs/bay-board", { params: { query: { company_id: companyId, branch_id: branchId, day: iso(start), days: DAYS } } })),
  });
  if (board.error) return <ErrorState title={t("garage.bays.loadFailed")} message={board.error.message} onRetry={() => void board.refetch()} />;
  const bays = board.data?.bays ?? [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {branches.length > 1 && <Select aria-label={t("filters.branch")} className="w-auto" value={branchId} onChange={(e) => setBranchId(e.target.value)}>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select>}
        <Button variant="secondary" size="sm" onClick={() => setStart(addDays(start, -DAYS))}><ChevronLeft className="h-4 w-4" />{t("garage.bays.earlier")}</Button>
        <Button variant="secondary" size="sm" onClick={() => setStart(new Date())}>{t("garage.bays.today")}</Button>
        <Button variant="secondary" size="sm" onClick={() => setStart(addDays(start, DAYS))}>{t("garage.bays.later")}<ChevronRight className="h-4 w-4" /></Button>
      </div>
      {!board.data ? <Skeleton className="h-48" /> : bays.length === 0 ? <EmptyState title={t("garage.bays.noBays")} hint={t("garage.bays.noBaysHint")} /> : (
        <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-card">
          <table className="w-full min-w-[56rem] table-fixed border-collapse text-sm">
            <thead>
              <tr className="border-b border-line bg-sunken/60 text-xs text-muted">
                <th scope="col" className="w-28 px-3 py-2 text-left font-medium">{t("garage.bays.bay")}</th>
                {days.map((d) => <th key={iso(d)} scope="col" className="px-2 py-2 text-left font-medium">{formatDate(iso(d))}</th>)}
              </tr>
            </thead>
            <tbody>
              {bays.map((bay) => (
                <tr key={bay.id} className="border-b border-line last:border-0 align-top">
                  <th scope="row" className="px-3 py-2 text-left font-semibold">{bay.name}</th>
                  {days.map((d) => {
                    const here = (board.data?.bookings ?? []).filter((b) => b.bay_id === bay.id && new Date(b.starts_at).toDateString() === d.toDateString());
                    return (
                      <td key={iso(d)} className="min-h-16 space-y-1 border-l border-line px-1.5 py-1.5">
                        {here.map((b) => (
                          <Link key={b.id} to={jobHref(b.job_id)} className="block rounded-md bg-brand-soft px-2 py-1 text-xs hover:bg-brand-soft/70">
                            <span className="tnum block font-medium">{new Date(b.starts_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}–{new Date(b.ends_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                            <span className="block truncate">{b.job_number} {b.item ?? b.job_title}</span>
                          </Link>
                        ))}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
