import { type FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  Alert, api, Button, Card, EmptyState, ErrorState, Field, FormGrid, Input, Select, Skeleton, today, unwrap, useCompany, useMutation, useQuery, useTranslation,
} from "@/sdk";

import { DownloadButton } from "./DownloadButton";

/** Step 1: what kind of data, for which company, and the file. */
export function UploadStep() {
  const { t } = useTranslation("imports");
  const navigate = useNavigate();
  const { companies } = useCompany();
  const kinds = useQuery({ queryKey: ["import-kinds"], queryFn: () => unwrap(api.GET("/api/v1/imports/kinds")) });
  const [params] = useSearchParams();
  const [kind, setKind] = useState(params.get("kind") ?? "");
  const [goLive, setGoLive] = useState("");
  const [tolerance, setTolerance] = useState("0");
  const [companyId, setCompanyId] = useState("");
  const [decimal, setDecimal] = useState<"." | ",">(".");
  const [dateFormat, setDateFormat] = useState<"iso" | "dmy" | "mdy">("iso");
  const [file, setFile] = useState<File | null>(null);
  const chosen = kinds.data?.find((k) => k.kind === kind);
  const company = companyId || companies[0]?.id || "";

  const upload = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/imports/batches", {
      params: { query: {
        kind, company_id: company, filename: file!.name, decimal_separator: decimal, date_format: dateFormat,
        ...(chosen?.needs_go_live ? { as_of: goLive } : {}), ...(chosen?.whole_file ? { tolerance } : {}),
      } },
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
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,14rem),1fr))] gap-3">
          {kinds.data.map((k) => (
            <label key={k.kind} className={`min-w-0 cursor-pointer rounded-xl border p-3 transition-colors ${kind === k.kind ? "border-brand bg-brand/5" : "border-line hover:bg-sunken"}`}>
              <input type="radio" name="kind" className="sr-only" checked={kind === k.kind} onChange={() => setKind(k.kind)} />
              <span className="block font-medium [overflow-wrap:anywhere]">{k.title}</span>
              <span className="mt-1 block text-sm text-muted [overflow-wrap:anywhere]">{k.description}</span>
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
              {chosen.needs_go_live && (
                <Field label={t("upload.goLive")} hint={t("upload.goLiveHint")} required>
                  <Input type="date" value={goLive} max={today()} onChange={(e) => setGoLive(e.target.value)} />
                </Field>
              )}
              {chosen.whole_file && (
                <Field label={t("upload.tolerance")} hint={t("upload.toleranceHint")}>
                  <Input inputMode="decimal" value={tolerance} onChange={(e) => setTolerance(e.target.value)} />
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
            {chosen.needs_go_live && (
              <Alert tone="info">{t("upload.openingOrder")} <Link to="/imports/opening-balances" className="font-medium underline">{t("upload.openingGuide")}</Link></Alert>
            )}
            {chosen.reversible ? null : <Alert tone="info">{chosen.reversal_note || t("upload.notReversible")}</Alert>}
            {upload.error && <Alert tone="bad">{upload.error.message}</Alert>}
          </div>
        </Card>
      )}

      <div className="flex justify-end">
        <Button type="submit" loading={upload.isPending} disabled={!chosen || !file || !company || (chosen.needs_go_live && !goLive) || (chosen.whole_file && !(Number(tolerance) >= 0))}>{t("upload.next")}</Button>
      </div>
    </form>
  );
}
