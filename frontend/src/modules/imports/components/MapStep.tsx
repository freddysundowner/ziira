import { useMemo, useState } from "react";

import {
  Alert, api, Button, Card, Field, FormGrid, Select, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { type Batch, mappingProblems } from "../lib/wizard";

const PREVIEW_ROWS = 5;

/** Step 2: which column of the file is which field, with a look at the first rows. */
export function MapStep({ batch }: { batch: Batch }) {
  const { t } = useTranslation("imports");
  const qc = useQueryClient();
  const [mapping, setMapping] = useState<Record<string, string | null>>(batch.mapping);
  const [decimal, setDecimal] = useState(batch.options.decimal_separator as "." | ",");
  const [dateFormat, setDateFormat] = useState(batch.options.date_format as "iso" | "dmy" | "mdy");
  const preview = useQuery({
    queryKey: ["import-preview", batch.id],
    queryFn: () => unwrap(api.GET("/api/v1/imports/batches/{batch_id}/rows", { params: { path: { batch_id: batch.id }, query: { limit: PREVIEW_ROWS } } })),
  });
  const problems = useMemo(() => mappingProblems(batch.columns, mapping), [batch.columns, mapping]);

  const check = useMutation({
    meta: { silent: true },
    mutationFn: async () => {
      await unwrap(api.PUT("/api/v1/imports/batches/{batch_id}/mapping", {
        params: { path: { batch_id: batch.id } }, body: { columns: mapping, decimal_separator: decimal, date_format: dateFormat } }));
      return unwrap(api.POST("/api/v1/imports/batches/{batch_id}/validate", { params: { path: { batch_id: batch.id } } }));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["import", batch.id] }),
    onError: (e) => toast(e.message, "bad"),
  });
  const blocked = problems.missing.length > 0 || problems.duplicated.length > 0;

  return (
    <div className="space-y-4">
      {batch.warnings.map((w) => <Alert key={w} tone="warn">{w}</Alert>)}
      <Card title={t("map.title")} description={t("map.hint", { file: batch.filename, count: batch.total_rows })}>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            {batch.columns.map((c) => (
              <Field key={c.name} label={`${c.name}${c.required ? " *" : ""}`} hint={`${c.description} ${t("map.example", { value: c.example })}`}>
                <Select value={mapping[c.name] ?? ""} onChange={(e) => setMapping((m) => ({ ...m, [c.name]: e.target.value || null }))}>
                  <option value="">{c.required ? t("map.choose") : t("map.notInFile")}</option>
                  {batch.headers.map((h) => <option key={h} value={h}>{h}</option>)}
                </Select>
              </Field>
            ))}
          </div>
          <FormGrid>
            <Field label={t("upload.decimal")}>
              <Select value={decimal} onChange={(e) => setDecimal(e.target.value as "." | ",")}>
                <option value=".">{t("upload.point")}</option><option value=",">{t("upload.comma")}</option>
              </Select>
            </Field>
            <Field label={t("upload.dates")}>
              <Select value={dateFormat} onChange={(e) => setDateFormat(e.target.value as "iso")}>
                <option value="iso">{t("upload.iso")}</option><option value="dmy">{t("upload.dmy")}</option><option value="mdy">{t("upload.mdy")}</option>
              </Select>
            </Field>
          </FormGrid>
          {problems.missing.length > 0 && <Alert tone="warn">{t("map.missing", { fields: problems.missing.join(", ") })}</Alert>}
          {problems.duplicated.length > 0 && <Alert tone="warn">{t("map.duplicated", { columns: problems.duplicated.join(", ") })}</Alert>}
        </div>
      </Card>

      <Card title={t("map.preview")} description={t("map.previewHint", { count: PREVIEW_ROWS })} flush>
        {preview.isLoading ? <p className="p-4 text-sm text-muted">…</p> : preview.error ? (
          <p className="p-4 text-sm text-bad">{preview.error.message} <button className="underline" onClick={() => void preview.refetch()}>{t("retry")}</button></p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-sunken text-xs uppercase tracking-wide text-muted">
                <tr><th className="px-3 py-2">#</th>{batch.headers.map((h) => <th key={h} className="whitespace-nowrap px-3 py-2">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-line">
                {(preview.data?.rows ?? []).map((r) => (
                  <tr key={r.row_no}><td className="px-3 py-2 text-muted">{r.row_no}</td>{r.raw.map((cell, i) => <td key={i} className="whitespace-nowrap px-3 py-2">{cell}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="flex justify-end">
        <Button loading={check.isPending} disabled={blocked} onClick={() => check.mutate()}>{t("map.next")}</Button>
      </div>
    </div>
  );
}
