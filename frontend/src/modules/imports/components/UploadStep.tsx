import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  Alert, api, Button, Card, EmptyState, ErrorState, Field, FormGrid, Select, Skeleton, unwrap, useCompany, useMutation, useQuery, useTranslation,
} from "@/sdk";

import { DownloadButton } from "./DownloadButton";

/** Step 1: what kind of data, for which company, and the file. */
export function UploadStep() {
  const { t } = useTranslation("imports");
  const navigate = useNavigate();
  const { companies } = useCompany();
  const kinds = useQuery({ queryKey: ["import-kinds"], queryFn: () => unwrap(api.GET("/api/v1/imports/kinds")) });
  const [kind, setKind] = useState("");
  const [companyId, setCompanyId] = useState("");
  const [decimal, setDecimal] = useState<"." | ",">(".");
  const [dateFormat, setDateFormat] = useState<"iso" | "dmy" | "mdy">("iso");
  const [file, setFile] = useState<File | null>(null);
  const chosen = kinds.data?.find((k) => k.kind === kind);
  const company = companyId || companies[0]?.id || "";

  const upload = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/imports/batches", {
      params: { query: { kind, company_id: company, filename: file!.name, decimal_separator: decimal, date_format: dateFormat } },
      body: file as unknown as string,
      bodySerializer: (body) => body as BodyInit,
      headers: { "Content-Type": "application/octet-stream" },
    })),
    onSuccess: (batch) => navigate(`/imports/${batch.id}`),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); upload.mutate(); };

  if (kinds.isLoading) return <Skeleton className="h-48 w-full" />;
  if (kinds.error) return <ErrorState message={kinds.error.message} onRetry={() => void kinds.refetch()} />;
  if (!kinds.data?.length) return <Card><EmptyState title={t("noKinds")} hint={t("noKindsHint")} /></Card>;

  return (
    <form onSubmit={submit} className="space-y-4">
      <Card title={t("upload.what")} description={t("upload.whatHint")}>
        <div className="grid gap-3 sm:grid-cols-2">
          {kinds.data.map((k) => (
            <label key={k.kind} className={`cursor-pointer rounded-xl border p-3 transition-colors ${kind === k.kind ? "border-brand bg-brand/5" : "border-line hover:bg-sunken"}`}>
              <input type="radio" name="kind" className="sr-only" checked={kind === k.kind} onChange={() => setKind(k.kind)} />
              <span className="block font-medium">{k.title}</span>
              <span className="mt-1 block text-sm text-muted">{k.description}</span>
            </label>
          ))}
        </div>
      </Card>

      {chosen && (
        <Card title={t("upload.file")} description={t("upload.fileHint")}
          actions={<DownloadButton fileName={`import-${chosen.kind}-template.csv`} request={() => api.GET("/api/v1/imports/kinds/{kind}/template", { params: { path: { kind: chosen.kind } }, parseAs: "blob" })}>{t("upload.template")}</DownloadButton>}>
          <div className="space-y-4">
            <FormGrid>
              {companies.length > 1 && (
                <Field label={t("upload.company")}>
                  <Select value={company} onChange={(e) => setCompanyId(e.target.value)}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
                </Field>
              )}
              <Field label={t("upload.decimal")} hint={t("upload.decimalHint")}>
                <Select value={decimal} onChange={(e) => setDecimal(e.target.value as "." | ",")}>
                  <option value=".">{t("upload.point")}</option><option value=",">{t("upload.comma")}</option>
                </Select>
              </Field>
              <Field label={t("upload.dates")} hint={t("upload.datesHint")}>
                <Select value={dateFormat} onChange={(e) => setDateFormat(e.target.value as "iso")}>
                  <option value="iso">{t("upload.iso")}</option><option value="dmy">{t("upload.dmy")}</option><option value="mdy">{t("upload.mdy")}</option>
                </Select>
              </Field>
            </FormGrid>
            <Field label={t("upload.pick")} hint={t("upload.pickHint")}>
              <input type="file" accept=".csv,.txt,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full text-sm file:mr-3 file:rounded-lg file:border file:border-line file:bg-surface file:px-3 file:py-2 file:text-sm file:font-medium hover:file:bg-sunken" />
            </Field>
            {chosen.reversible ? null : <Alert tone="info">{chosen.reversal_note || t("upload.notReversible")}</Alert>}
            {upload.error && <Alert tone="bad">{upload.error.message}</Alert>}
          </div>
        </Card>
      )}

      <div className="flex justify-end">
        <Button type="submit" loading={upload.isPending} disabled={!chosen || !file || !company}>{t("upload.next")}</Button>
      </div>
    </form>
  );
}
