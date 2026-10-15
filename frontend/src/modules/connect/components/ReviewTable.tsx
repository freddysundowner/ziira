import { useState } from "react";

import { Button, Input, useTranslation } from "@/sdk";

import type { Preview } from "../uploadLogic";

/** The lines that could not be trusted, with their cells open for correcting (only for pictures: the lines wait here). */
export function ReviewTable({ preview, busy, onSave }: { preview: Preview; busy: boolean; onSave: (fixes: { row: number; column: number; value: string }[]) => void }) {
  const { t } = useTranslation("connect");
  const [edits, setEdits] = useState<Record<string, string>>({});
  const shown = preview.headers.map((h, i) => ({ h, i })).filter(({ i }) => preview.review_rows.some((r) => r.cells[i]));
  const save = () => onSave(Object.entries(edits).map(([key, value]) => { const [row, column] = key.split(":").map(Number); return { row, column, value }; }));
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">{t("upload.correctTitle")}</p>
      <p className="text-sm text-muted">{t("upload.correctHint")}</p>
      <div className="space-y-3">
        {preview.review_rows.map((r) => (
          <div key={r.row} className="rounded-xl border border-bad/40 bg-bad-soft/30 p-3">
            <p className="mb-2 text-xs text-bad">{t("upload.lineProblem", { row: r.row, problem: r.problem })}</p>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {shown.map(({ h, i }) => (
                <label key={h} className="block text-xs text-muted">{h}
                  <Input className="mt-0.5" value={edits[`${r.row}:${i}`] ?? r.cells[i] ?? ""} aria-label={`${h}, ${t("upload.line")} ${r.row}`}
                    onChange={(e) => setEdits((cur) => ({ ...cur, [`${r.row}:${i}`]: e.target.value }))} />
                </label>
              ))}
            </div>
          </div>
        ))}
      </div>
      <Button variant="secondary" loading={busy} disabled={Object.keys(edits).length === 0} onClick={save}>{t("upload.saveCorrections")}</Button>
    </div>
  );
}
