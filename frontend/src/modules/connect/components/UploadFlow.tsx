import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Alert, api, Button, Card, Field, Input, Select, type Schemas, Spinner, unwrap, useCurrency, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

import { hintsFor, issuesCsv, type Preview, takePendingFile } from "../uploadLogic";
import { DropZone } from "./DropZone";
import { type Fix, GuidedFix } from "./GuidedFix";
import { ReviewTable } from "./ReviewTable";
import { Summary } from "./Summary";

type Kind = Schemas["ConnectorKindOut"];
type Source = { file: File | null; password: string; scanId: string | null };
const EMPTY: Source = { file: null, password: "", scanId: null };

/**
 * Add a file or statement: drop it, we work out what is in it and say so in a sentence, the person says "Looks right"
 * (or fixes what is wrong in a few plain choices), and the readable lines are stored. Pictures are read in the
 * background and always have to be checked by the person before anything is stored.
 */
export function UploadFlow({ connectionId, kind, companyId, onDone }: { connectionId: string; kind: Kind; companyId: string; onDone?: () => void }) {
  const { t } = useTranslation("connect");
  const queryClient = useQueryClient();
  const currency = useCurrency(companyId);
  const family = hintsFor(kind.entities);
  const statement = family === "statement";
  const [source, setSource] = useState<Source>(EMPTY);
  const [password, setPassword] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [fixing, setFixing] = useState(false);
  const [result, setResult] = useState<{ new: number; changed: number; skipped: number } | null>(null);
  const ocr = useQuery({ queryKey: ["connect", "ocr"], queryFn: () => unwrap(api.GET("/api/v1/connect/ocr")), staleTime: 60_000 });

  const send = (mode: "preview" | "commit", src: Source) =>
    unwrap(api.POST("/api/v1/connect/connections/{connection_id}/upload", {
      params: { path: { connection_id: connectionId }, query: { mode, filename: src.file?.name ?? "picture", scan_id: src.scanId ?? undefined } },
      body: (src.file ?? new Uint8Array(0)) as unknown as string,
      bodySerializer: (body) => body as BodyInit,
      headers: { "Content-Type": "application/octet-stream", ...(src.password ? { "X-File-Password": src.password } : {}) },
    }));

  const show = (r: Schemas["FileUploadOut"], src: Source) => {
    const p = r.preview;
    if (p.state === "reading" && p.scan) { setSource({ ...src, scanId: p.scan.id }); setPreview(p); return; }
    setPreview(p);
    setFixing(p.state === "ready" && (p.missing.length > 0 || (p.confidence < 0.6 && p.source !== "scan")));
  };
  const check = useMutation({ meta: { silent: true }, mutationFn: (src: Source) => send("preview", src), onSuccess: (r, src) => show(r, src) });
  const fix = useMutation({
    meta: { silent: true },
    mutationFn: async (f: Fix) => {
      await unwrap(api.PUT("/api/v1/connect/connections/{connection_id}/file-settings", {
        params: { path: { connection_id: connectionId } },
        body: { mapping: f.mapping, decimal_separator: f.decimal_separator, date_format: f.date_format },
      }));
      return send("preview", source);
    },
    onSuccess: (r) => { show(r, source); setFixing(false); },
  });
  const correct = useMutation({
    meta: { silent: true },
    mutationFn: async (fixes: { row: number; column: number; value: string }[]) => {
      await unwrap(api.PATCH("/api/v1/connect/connections/{connection_id}/scans/{scan_id}", { params: { path: { connection_id: connectionId, scan_id: source.scanId! } }, body: { fixes } }));
      return send("preview", source);
    },
    onSuccess: (r) => show(r, source),
  });
  const commit = useMutation({
    meta: { silent: true },
    mutationFn: () => send("commit", source),
    onSuccess: (r) => {
      setResult({ new: r.new, changed: r.changed, skipped: r.skipped });
      void queryClient.invalidateQueries({ queryKey: ["connect"] });
      setSource((s) => ({ ...s, password: "" }));
      onDone?.();
    },
  });

  // a picture is read in the background: watch it until it is ready, then ask for the preview of what was read
  const reading = preview?.state === "reading" && source.scanId !== null;
  const scan = useQuery({
    queryKey: ["connect", "scan", source.scanId], enabled: reading, refetchInterval: 1500,
    queryFn: () => unwrap(api.GET("/api/v1/connect/connections/{connection_id}/scans/{scan_id}", { params: { path: { connection_id: connectionId, scan_id: source.scanId! } } })),
  });
  const asked = useRef<string | null>(null);
  useEffect(() => {
    if (scan.data?.status === "ready" && asked.current !== source.scanId) { asked.current = source.scanId; check.mutate(source); }
  }, [scan.data?.status, source.scanId]); // eslint-disable-line react-hooks/exhaustive-deps

  const begin = (file: File, pw = "") => {
    const src = { file, password: pw, scanId: null };
    setSource(src); setPreview(null); setResult(null); setFixing(false); asked.current = null;
    check.mutate(src);
  };
  useEffect(() => { // a file dropped on the first screen of the wizard waits here
    const waiting = takePendingFile();
    if (waiting) begin(waiting.file, waiting.password);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const reset = () => { setSource(EMPTY); setPassword(""); setPreview(null); setResult(null); setFixing(false); asked.current = null; check.reset(); };

  const busy = check.isPending || fix.isPending || correct.isPending;
  const error = check.error ?? fix.error ?? correct.error ?? commit.error;
  const download = () => {
    if (!preview) return;
    const blob = new Blob([issuesCsv(preview, { line: t("upload.line"), problem: t("upload.problem") })], { type: "text/csv" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "lines-left-out.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  };
  const entityTitle = t(`upload.thing.${family}`);

  if (result) {
    return (
      <Card title={t("upload.doneTitle")}>
        <div className="space-y-4">
          <Alert tone="ok">{t("upload.done", { new: result.new, already: Math.max((preview?.valid_rows ?? 0) - result.new - result.changed, 0), skipped: preview?.issue_count ?? 0 })}</Alert>
          <div>
            <p className="font-medium">{t("upload.nextTitle")}</p>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">{[1, 2, 3].map((n) => <li key={n}>{t(`upload.next.${family}.${n}`)}</li>)}</ul>
            <p className="mt-2 text-sm text-muted">{t("upload.nextWhen")} <Link className="text-brand-strong underline" to="/intel">{t("upload.nextLink")}</Link></p>
          </div>
          <Button variant="secondary" onClick={reset}>{t("upload.another")}</Button>
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card title={t(statement ? "upload.titleStatement" : "upload.title")} description={kind.how_to}>
        <div className="space-y-4">
          {!source.file && !busy && !preview && (
            <DropZone onFile={begin} statement={statement} picturesOk={ocr.data?.available} />
          )}
          {source.file && (
            <p className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium">{source.file.name}</span>
              <Button variant="ghost" size="sm" onClick={reset}>{t("upload.different")}</Button>
            </p>
          )}
          {check.isPending && !reading && <p className="flex items-center gap-2 text-sm text-muted" role="status"><Spinner />{t("upload.checking")}</p>}
          {reading && (
            <div className="space-y-2" role="status">
              <p className="flex items-center gap-2 text-sm"><Spinner />{t("upload.readingPicture", { done: scan.data?.pages_done ?? 0, total: scan.data?.pages ?? preview?.scan?.pages ?? 1 })}</p>
              <div className="h-2 overflow-hidden rounded-full bg-sunken" role="progressbar" aria-valuemin={0} aria-valuemax={scan.data?.pages ?? 1} aria-valuenow={scan.data?.pages_done ?? 0}>
                <div className="h-full bg-brand transition-all" style={{ width: `${Math.round(((scan.data?.pages_done ?? 0) / (scan.data?.pages ?? 1)) * 100)}%` }} />
              </div>
              <p className="text-xs text-muted">{t("upload.readingNote")}</p>
              {scan.data?.status === "failed" && <Alert tone="bad">{scan.data.error}</Alert>}
            </div>
          )}
          {preview && (preview.state === "password_required" || preview.state === "wrong_password") && (
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (source.file) begin(source.file, password); }}>
              <Alert tone={preview.state === "wrong_password" ? "bad" : "info"}>{preview.state === "wrong_password" ? t("upload.wrongPassword") : t("upload.passwordNeeded")}</Alert>
              <Field label={t("upload.password")} hint={t("upload.passwordHint")}>
                <Input type="password" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus required />
              </Field>
              <Button type="submit" loading={busy} disabled={!password}>{t("upload.openFile")}</Button>
            </form>
          )}
          {preview?.state === "failed" && <Alert tone="bad">{preview.message}</Alert>}
          {error && <Alert tone="bad">{error.message}</Alert>}
        </div>
      </Card>

      {preview?.state === "ready" && (
        <Card title={t("upload.foundTitle")}>
          <div className="space-y-4">
            <Summary preview={preview} currency={currency} entityTitle={entityTitle} />
            {preview.date_ambiguous && !fixing && (
              <Field label={t("upload.whichDate", { example: preview.date_examples[0] ?? "" })} hint={t("upload.whichDateHint")}>
                <Select value="" onChange={(e) => e.target.value && fix.mutate({ mapping: Object.fromEntries(preview.fields.filter((f) => f.column).map((f) => [f.name, f.column])), date_format: e.target.value as Fix["date_format"], decimal_separator: preview.settings.decimal_separator as Fix["decimal_separator"] })}>
                  <option value="">{t("upload.chooseOne")}</option>
                  <option value="dmy">{t("upload.dateDmy")}</option>
                  <option value="mdy">{t("upload.dateMdy")}</option>
                </Select>
              </Field>
            )}
            {preview.source === "scan" && !fixing && preview.review_rows.length > 0 && (
              <ReviewTable key={preview.review_rows.map((r) => r.row).join(",")} preview={preview} busy={correct.isPending} onSave={(fixes) => correct.mutate(fixes)} />
            )}
            {preview.issue_count > 0 && (
              <div className="rounded-xl bg-sunken p-3 text-sm">
                <p>{t("upload.leftOut", { count: preview.issue_count })}</p>
                <ul className="mt-1 max-h-40 list-disc space-y-0.5 overflow-auto pl-5 text-xs text-muted">
                  {preview.issues.slice(0, 20).map((i) => <li key={`${i.row}-${i.message}`}>{t("upload.lineProblem", { row: i.row, problem: i.message })}</li>)}
                </ul>
                <Button className="mt-2" variant="ghost" size="sm" onClick={download}>{t("upload.download")}</Button>
              </div>
            )}
            {fixing ? (
              <GuidedFix preview={preview} busy={fix.isPending} onApply={(f) => fix.mutate(f)} onCancel={() => setFixing(false)} />
            ) : (
              <div className="flex flex-wrap gap-2">
                <Button loading={commit.isPending}
                  disabled={preview.missing.length > 0 || preview.valid_rows === 0 || preview.date_ambiguous || busy}
                  onClick={() => commit.mutate()}>{t("upload.looksRight")}</Button>
                <Button variant="secondary" onClick={() => setFixing(true)}>{t("upload.somethingWrong")}</Button>
              </div>
            )}
            {preview.date_ambiguous && !fixing && <p className="text-xs text-muted">{t("upload.chooseDateFirst")}</p>}
          </div>
        </Card>
      )}
    </div>
  );
}
