import { ChevronLeft, ChevronRight, Clock, Receipt } from "lucide-react";
import { useState } from "react";

import { Alert, api, Button, Card, ConfirmDialog, ErrorState, formatDate, PageHeader, Skeleton, today, unwrap, useMutation, useQuery, useTranslation } from "@/sdk";

import { CompanyPicker } from "../components/CompanyBar";
import { ExpenseDialog } from "../components/ExpenseDialog";
import { LogTimeDialog } from "../components/LogTimeDialog";
import { TimerBar } from "../components/TimerBar";
import { WeekGrid } from "../components/WeekGrid";
import { ExpenseList, EntryList } from "../components/WeekLists";
import { WeekStatus } from "../components/WeekStatus";
import { useRefresh, useSettings, useWorkCompany } from "../hooks";
import { addDays, formatDuration, type GridRow, type RowSeed, weekDays, weekStartOf } from "../lib";
import type { Entry, Expense, Week } from "../types";

/** My week: the timer, the week grid, expenses and sending the week for approval. */
export default function MyWeekPage() {
  const { t } = useTranslation("timebilling");
  const { companyId, companies, setCompanyId, currency } = useWorkCompany();
  const settings = useSettings(companyId);
  const refresh = useRefresh();
  const [anchor, setAnchor] = useState(today());
  const weekStart = weekStartOf(anchor, settings.data?.week_starts_on ?? 1);
  const days = weekDays(weekStart);
  const [seeds, setSeeds] = useState<RowSeed[]>([]);
  const [logging, setLogging] = useState<{ entry: Entry | null } | null>(null);
  const [spending, setSpending] = useState<{ expense: Expense | null } | null>(null);
  const [removing, setRemoving] = useState<{ kind: "entry"; id: string } | { kind: "expense"; id: string } | null>(null);

  const week = useQuery<Week>({
    queryKey: ["timebilling", "week", companyId, weekStart], enabled: !!companyId && !!settings.data,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/weeks/mine", { params: { query: { company_id: companyId, week_start: weekStart } } })),
  });
  const saveCell = useMutation({
    mutationFn: ({ row, day, minutes }: { row: GridRow; day: string; minutes: number }) =>
      unwrap(api.PUT("/api/v1/timebilling/grid", { body: { cells: [{ project_id: row.project_id, work_date: day, minutes, task: row.task, billable: row.billable }] } })),
    onSettled: () => void refresh(),
  });
  const remove = useMutation({
    mutationFn: async (what: NonNullable<typeof removing>) => {
      if (what.kind === "entry") await unwrap(api.DELETE("/api/v1/timebilling/entries/{entry_id}", { params: { path: { entry_id: what.id } } }));
      else await unwrap(api.DELETE("/api/v1/timebilling/expenses/{expense_id}", { params: { path: { expense_id: what.id } } }));
    },
    onSuccess: () => { setRemoving(null); void refresh(); },
  });

  const missing = useQuery({
    queryKey: ["timebilling", "missing", companyId], enabled: !!companyId && !!settings.data?.nudge_minutes,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/my/missing", { params: { query: { company_id: companyId } } })),
  });
  const data = week.data;
  const editable = !!data && (data.status === "draft" || data.status === "rejected");
  const step = settings.data?.minute_step ?? 1;
  const defaultDay = days.includes(today()) ? today() : weekDays(weekStart)[0] ?? today();

  return (
    <>
      <PageHeader title={t("myWeek.title")} description={t("myWeek.hint")}
        actions={<>
          <CompanyPicker companies={companies} value={companyId} onChange={setCompanyId} />
          {editable && <Button variant="secondary" onClick={() => setLogging({ entry: null })}><Clock className="h-4 w-4" />{t("log.button")}</Button>}
          {editable && <Button variant="secondary" onClick={() => setSpending({ expense: null })}><Receipt className="h-4 w-4" />{t("expenses.add")}</Button>}
        </>} />
      <div className="space-y-4">
        {!!missing.data?.length && (
          <Alert tone="warn">
            <p className="font-medium">{t("myWeek.missing")}</p>
            <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
              {missing.data.slice(0, 6).map((m) => <li key={m.day}><button className="underline" onClick={() => setAnchor(m.day)}>{formatDate(m.day)}: {formatDuration(m.logged_minutes)} / {formatDuration(m.wanted_minutes)}</button></li>)}
            </ul>
          </Alert>
        )}
        {companyId && <TimerBar companyId={companyId} />}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-1">
            <Button variant="secondary" size="sm" aria-label={t("week.previous")} onClick={() => setAnchor(addDays(weekStart, -7))}><ChevronLeft className="h-4 w-4" /></Button>
            <Button variant="secondary" size="sm" aria-label={t("week.next")} onClick={() => setAnchor(addDays(weekStart, 7))}><ChevronRight className="h-4 w-4" /></Button>
            <h2 className="ml-2 text-base font-semibold">{formatDate(weekStart)} – {formatDate(addDays(weekStart, 6))}</h2>
          </div>
          <Button variant="ghost" size="sm" disabled={weekStart === weekStartOf(today(), settings.data?.week_starts_on ?? 1)} onClick={() => setAnchor(today())}>{t("week.thisWeek")}</Button>
        </div>

        {(week.isLoading || settings.isLoading) && <Skeleton className="h-64 w-full" />}
        {(week.error || settings.error) && <ErrorState message={(week.error ?? settings.error)?.message} onRetry={() => { void week.refetch(); void settings.refetch(); }} />}
        {data && (
          <>
            <WeekStatus week={data} companyId={companyId} />
            <WeekGrid companyId={companyId} days={days} entries={data.entries} seeds={seeds} onSeeds={setSeeds} step={step} readOnly={!editable} saving={saveCell.isPending}
              onSave={(row, day, minutes) => saveCell.mutate({ row, day, minutes })} />
            <Card title={t("entries.title")} description={t("entries.hint")} flush>
              <EntryList entries={data.entries.filter((e) => e.source !== "grid")} canEdit={editable} onEdit={(entry) => setLogging({ entry })} onDelete={(e) => setRemoving({ kind: "entry", id: e.id })} />
            </Card>
            <Card title={t("expenses.title")} description={t("expenses.hint")} flush
              actions={editable && <Button variant="secondary" size="sm" onClick={() => setSpending({ expense: null })}>{t("expenses.add")}</Button>}>
              <ExpenseList expenses={data.expenses} currency={currency} canEdit={editable} onEdit={(expense) => setSpending({ expense })} onDelete={(x) => setRemoving({ kind: "expense", id: x.id })} />
            </Card>
          </>
        )}
      </div>
      <LogTimeDialog open={!!logging} onClose={() => setLogging(null)} companyId={companyId} entry={logging?.entry} day={defaultDay} step={step} />
      <ExpenseDialog open={!!spending} onClose={() => setSpending(null)} companyId={companyId} expense={spending?.expense} day={defaultDay} />
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} onConfirm={() => removing && remove.mutate(removing)} busy={remove.isPending} danger
        title={t("delete")} message={t(removing?.kind === "expense" ? "expenses.deleteAsk" : "entries.deleteAsk")} confirmLabel={t("delete")} />
    </>
  );
}
