import { Plus, Trash2 } from "lucide-react";

import { Button, cx, Field, IconButton, Input, useTranslation } from "@/sdk";

import { type AccessWindow, newWindow, toggleDay } from "../gymLogic";

const DAYS = [0, 1, 2, 3, 4, 5, 6] as const;

/** When a plan lets people in: windows of weekdays and times. No windows means any time. */
export function AccessWindows({ value, onChange }: { value: AccessWindow[]; onChange: (next: AccessWindow[]) => void }) {
  const { t } = useTranslation("memberships");
  const patch = (i: number, change: Partial<AccessWindow>) => onChange(value.map((w, j) => (j === i ? { ...w, ...change } : w)));
  return (
    <div className="space-y-3">
      {value.length === 0 && <p className="text-sm text-muted">{t("planx.anyTime")}</p>}
      {value.map((w, i) => (
        <div key={i} className="space-y-2 rounded-lg border border-line p-3">
          <div role="group" aria-label={t("planx.days")} className="flex flex-wrap gap-1.5">
            {DAYS.map((d) => (
              <button key={d} type="button" aria-pressed={w.days.includes(d)} onClick={() => patch(i, { days: toggleDay(w.days, d) })}
                className={cx("h-10 min-w-12 rounded-lg border px-3 text-sm font-semibold", w.days.includes(d) ? "border-brand bg-brand-soft text-brand-strong" : "border-line text-muted hover:bg-sunken")}>
                {t(`weekdays.${d}`)}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <Field label={t("planx.from")}><Input type="time" value={w.from} onChange={(e) => patch(i, { from: e.target.value })} /></Field>
            <Field label={t("planx.to")}><Input type="time" value={w.to === "24:00" ? "23:59" : w.to} onChange={(e) => patch(i, { to: e.target.value })} /></Field>
            <IconButton label={t("planx.removeWindow")} onClick={() => onChange(value.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></IconButton>
          </div>
        </div>
      ))}
      <Button type="button" variant="secondary" onClick={() => onChange([...value, newWindow()])}><Plus className="h-4 w-4" />{t("planx.addWindow")}</Button>
    </div>
  );
}
