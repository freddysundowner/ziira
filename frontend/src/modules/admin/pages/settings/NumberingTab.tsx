import { Pencil } from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  api, Button, DataTable, Field, FormGrid, humanise, Input, Modal, NumberInput, toast, unwrap, useCan, useCompany, useFormState, useMutation,
  useQuery, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

import { sampleNumber } from "./model";

type Series = Schemas["SeriesOut"];

export default function NumberingTab() {
  const { t } = useTranslation("kernel");
  const { companies } = useCompany();
  const canEdit = useCan("settings.manage");
  const [editing, setEditing] = useState<Series | null>(null);
  const series = useQuery({ queryKey: ["document-series"], queryFn: () => unwrap(api.GET("/api/v1/settings/document-series")) });
  const branchName = (s: Series) => companies.flatMap((c) => c.branches).find((b) => b.id === s.branch_id)?.name;
  return (
    <>
      <p className="mb-3 text-sm text-muted">{t("numberingHint")}</p>
      <DataTable
        rows={series.data} loading={series.isLoading} error={series.error?.message} onRetry={() => void series.refetch()} rowKey={(s) => s.id}
        searchText={(s) => `${s.doc_type} ${s.prefix}`} searchPlaceholder={t("searchSeries")} pageSize={20}
        empty={{ title: t("noSeries"), hint: t("noSeriesHint") }}
        columns={[
          { header: t("docType"), sortValue: (s) => s.doc_type, cell: (s) => <span className="font-medium">{humanise(s.doc_type)}</span> },
          { header: t("branch"), hideBelow: "md", cell: (s) => branchName(s) ?? t("allBranches") },
          { header: t("prefix"), hideBelow: "sm", cell: (s) => <code className="text-xs">{s.prefix}</code> },
          { header: t("nextNumber"), cell: (s) => <code className="text-xs">{sampleNumber(s.prefix, s.next_number, s.padding)}</code> },
          { header: "", align: "right", cell: (s) => canEdit && <Button size="sm" variant="ghost" aria-label={t("edit")} onClick={() => setEditing(s)}><Pencil className="h-4 w-4" /></Button> },
        ]}
      />
      <EditSeries series={editing} onClose={() => setEditing(null)} />
    </>
  );
}

function EditSeries({ series, onClose }: { series: Series | null; onClose: () => void }) {
  return <Modal open={!!series} onClose={onClose} title={series ? humanise(series.doc_type) : ""}>{series && <SeriesForm key={series.id} series={series} onClose={onClose} />}</Modal>;
}

function SeriesForm({ series, onClose }: { series: Series; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const f = useFormState({ prefix: series.prefix, padding: String(series.padding), next_number: String(series.next_number) });
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.PATCH("/api/v1/settings/document-series/{series_id}", {
      params: { path: { series_id: series.id } }, body: { prefix: f.values.prefix, padding: Number(f.values.padding), next_number: Number(f.values.next_number) },
    })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["document-series"] }); toast(t("seriesSaved"), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast(e.message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const valid = Number(f.values.padding) >= 1 && Number(f.values.next_number) >= series.next_number;
  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label={t("prefix")} error={f.error("prefix")}><Input {...f.bind("prefix")} maxLength={20} /></Field>
      <FormGrid>
        <Field label={t("padding")} hint={t("paddingHint")} error={f.error("padding")}><NumberInput value={f.values.padding} onChange={(v) => f.set("padding", v)} /></Field>
        <Field label={t("nextNumber")} hint={t("nextNumberHint")} error={f.error("next_number")}><NumberInput value={f.values.next_number} onChange={(v) => f.set("next_number", v)} /></Field>
      </FormGrid>
      <p className="text-sm text-muted">{t("preview")}: <code>{sampleNumber(f.values.prefix, Number(f.values.next_number) || 0, Number(f.values.padding) || 1)}</code></p>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button type="submit" loading={save.isPending} disabled={!valid}>{t("save")}</Button>
      </div>
    </form>
  );
}
