import { Plus, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Button, cx, Field, IconButton, Switch, toast, today, useTranslation } from "@/sdk";

import {
  buildRows, dayName, dayNumber, dayTotals, formatClock, formatDuration, gridMinutesFor, parseDuration, rowKey, rowTotal, snapMinutes, type GridRow, type RowSeed,
} from "../lib";
import type { Entry, Project } from "../types";
import { ProjectPicker } from "./ProjectPicker";
import { TaskInput } from "./TaskInput";

/** One box of the grid: shows h:mm, takes 1.5 or 1:30, and saves when the person leaves it. */
function CellBox({ minutes, disabled, label, onCommit }: { minutes: number; disabled: boolean; label: string; onCommit: (minutes: number) => void }) {
  const { t } = useTranslation("timebilling");
  const [text, setText] = useState(formatClock(minutes));
  const [bad, setBad] = useState(false);
  useEffect(() => { setText(formatClock(minutes)); setBad(false); }, [minutes]);
  function commit() {
    const parsed = parseDuration(text);
    if (parsed === null) { setBad(true); toast(t("timeInvalid"), "bad"); return; }
    setBad(false);
    if (parsed !== minutes) onCommit(parsed);
    else setText(formatClock(minutes));
  }
  return (
    <input value={text} disabled={disabled} aria-label={label} aria-invalid={bad || undefined} inputMode="text" autoComplete="off" placeholder="–"
      onChange={(e) => setText(e.target.value)} onBlur={commit} onFocus={(e) => e.target.select()}
      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); (e.target as HTMLInputElement).blur(); } if (e.key === "Escape") { setText(formatClock(minutes)); setBad(false); } }}
      className={cx("tnum h-9 w-full min-w-[3.5rem] rounded-md border bg-surface px-1.5 text-center text-sm placeholder:text-muted hover:border-muted/50 disabled:cursor-not-allowed disabled:border-transparent disabled:bg-transparent", bad ? "border-bad" : "border-line", minutes > 0 && "font-medium")} />
  );
}

/** The week as a table: a row per project and task, a column per day. Cells save one at a time. */
export function WeekGrid({ companyId, days, entries, seeds, onSeeds, step, readOnly, saving, onSave }: {
  companyId: string; days: string[]; entries: readonly Entry[]; seeds: RowSeed[]; onSeeds: (seeds: RowSeed[]) => void; step: number; readOnly: boolean; saving: boolean;
  onSave: (row: GridRow, day: string, minutes: number) => void;
}) {
  const { t } = useTranslation("timebilling");
  const rows = buildRows(entries, seeds);
  const totals = dayTotals(rows, days);
  const week = totals.reduce((a, b) => a + b, 0);
  const todayIso = today();
  const [adding, setAdding] = useState(false);

  function commit(row: GridRow, day: string, typed: number) {
    const snapped = snapMinutes(typed, step);
    const stored = gridMinutesFor(snapped, row.cells[day]);
    if (stored === null) { toast(t("grid.belowOthers", { time: formatDuration((row.cells[day]?.total ?? 0) - (row.cells[day]?.own ?? 0)) }), "bad"); return; }
    if (snapped !== typed) toast(t("grid.snapped", { time: formatDuration(snapped), step }), "info");
    onSave(row, day, stored);
  }

  return (
    <div>
      <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-card">
        <table className="w-full min-w-[44rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line bg-sunken text-xs text-muted">
              <th scope="col" className="sticky left-0 z-[1] min-w-[11rem] bg-sunken px-3 py-2 text-left font-medium">{t("grid.rowHeader")}</th>
              {days.map((d) => (
                <th key={d} scope="col" className={cx("px-1 py-2 text-center font-medium", d === todayIso && "text-brand-strong")}>
                  <span className="block">{dayName(d)}</span><span className="tnum block text-sm text-ink">{dayNumber(d)}</span>
                </th>
              ))}
              <th scope="col" className="px-3 py-2 text-right font-medium">{t("grid.total")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={days.length + 2} className="px-4 py-8 text-center text-sm text-muted">{readOnly ? t("grid.emptyLocked") : t("grid.empty")}</td></tr>
            )}
            {rows.map((row) => (
              <tr key={row.key} className="border-b border-line last:border-0">
                <th scope="row" className="sticky left-0 z-[1] bg-surface px-3 py-1.5 text-left font-normal">
                  <p className="truncate font-medium">{row.project_code} · {row.project_name}</p>
                  <p className="truncate text-xs text-muted">{row.task ?? t("grid.noTask")}{!row.billable && ` · ${t("notBillable")}`}</p>
                </th>
                {days.map((d) => (
                  <td key={d} className="px-0.5 py-1">
                    <CellBox minutes={row.cells[d]?.total ?? 0} disabled={readOnly || saving || d > todayIso} label={`${row.project_code} ${row.task ?? ""} ${d}`} onCommit={(m) => commit(row, d, m)} />
                  </td>
                ))}
                <td className="tnum whitespace-nowrap px-3 py-1.5 text-right font-medium">{formatDuration(rowTotal(row, days))}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-line bg-sunken">
              <th scope="row" className="sticky left-0 bg-sunken px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-muted">{t("grid.dayTotal")}</th>
              {totals.map((m, i) => <td key={days[i]} className="tnum px-1 py-2 text-center text-xs font-medium">{m ? formatDuration(m) : "–"}</td>)}
              <td className="tnum whitespace-nowrap px-3 py-2 text-right text-sm font-semibold">{formatDuration(week)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted">{t("grid.hint")}{step > 1 && ` ${t("grid.stepHint", { step })}`}</p>
      {!readOnly && (adding ? (
        <AddRow companyId={companyId} existing={rows.map((r) => r.key)} onCancel={() => setAdding(false)} onAdd={(seed) => { onSeeds([...seeds, seed]); setAdding(false); }} />
      ) : (
        <Button variant="secondary" size="sm" className="mt-3" onClick={() => setAdding(true)}><Plus className="h-4 w-4" />{t("grid.addRow")}</Button>
      ))}
    </div>
  );
}

function AddRow({ companyId, existing, onAdd, onCancel }: { companyId: string; existing: string[]; onAdd: (seed: RowSeed) => void; onCancel: () => void }) {
  const { t } = useTranslation("timebilling");
  const [project, setProject] = useState<Project | null>(null);
  const [task, setTask] = useState("");
  const [billable, setBillable] = useState(true);
  const duplicate = !!project && existing.includes(rowKey(project.id, task, billable));
  return (
    <div className="mt-3 grid items-end gap-3 rounded-xl border border-line bg-surface p-3 shadow-card md:grid-cols-[minmax(0,2fr)_minmax(0,1.4fr)_auto_auto]">
      <Field label={t("projectField")}><ProjectPicker companyId={companyId} value={project?.id ?? ""} label={project ? `${project.code} · ${project.name}` : undefined} onChange={setProject} /></Field>
      <Field label={t("task")} error={duplicate ? t("grid.rowExists") : null}><TaskInput companyId={companyId} value={task} onChange={setTask} /></Field>
      <div className="flex items-center gap-2 pb-2 text-sm"><Switch checked={billable} onChange={setBillable} label={t("billable")} />{t("billable")}</div>
      <div className="flex items-center gap-2 pb-0.5">
        <Button disabled={!project || duplicate} onClick={() => project && onAdd({ project_id: project.id, project_code: project.code, project_name: project.name, task: task.trim() || null, billable })}>{t("grid.add")}</Button>
        <IconButton label={t("cancel")} onClick={onCancel}><X className="h-4 w-4" /></IconButton>
      </div>
    </div>
  );
}
