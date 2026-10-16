import { useEffect, useRef, useState } from "react";

import { api, Alert, Button, Drawer, Field, Select, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { usePaymentAccounts } from "./usePaymentAccounts";
import { usePaymentProviders } from "./usePaymentProviders";

/** Upload a provider's or bank's statement (CSV). Uploading the same one twice adds nothing. */
export function UploadStatement({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation("payments");
  const qc = useQueryClient();
  const accounts = usePaymentAccounts({ enabled: open });
  const fileInput = useRef<HTMLInputElement>(null);
  const [accountId, setAccountId] = useState("");
  const formats = usePaymentProviders(open).data?.statement_formats ?? [{ name: "bank", label: "" }];
  const [format, setFormat] = useState("bank");
  const [content, setContent] = useState("");
  const [fileName, setFileName] = useState("");
  const [readError, setReadError] = useState("");
  const [result, setResult] = useState<{ created: number; duplicates: number; skipped: string[] } | null>(null);

  useEffect(() => { if (open) { setAccountId(""); setContent(""); setFileName(""); setResult(null); setReadError(""); } }, [open]);

  const list = (accounts.data ?? []).filter((a) => a.kind === "mobile_money" || a.kind === "bank");
  const chosen = accountId || list[0]?.id || "";

  const upload = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/payments/accounts/{account_id}/statements", { params: { path: { account_id: chosen } }, body: { format, content } })),
    onSuccess: (r) => {
      setResult(r);
      void qc.invalidateQueries({ queryKey: ["transactions"] });
      toast(t("statementImported", { count: r.created }), "ok");
    },
    onError: (e) => toast((e as Error).message, "bad"),
  });

  async function pick(file: File | undefined) {
    setReadError("");
    if (!file) return;
    try {
      setContent(await file.text());
      setFileName(file.name);
    } catch {
      setContent(""); setFileName(""); setReadError(t("fileUnreadable"));
    }
  }

  return (
    <Drawer open={open} onClose={onClose} title={t("uploadStatement")}
      footer={<><Button variant="secondary" onClick={onClose}>{result ? t("close") : t("cancel")}</Button>{!result && <Button loading={upload.isPending} disabled={!content || !chosen} onClick={() => upload.mutate()}>{t("upload")}</Button>}</>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("uploadHint")}</p>
        <Field label={t("account")}>
          <Select value={chosen} onChange={(e) => setAccountId(e.target.value)}>{list.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select>
        </Field>
        <Field label={t("statementFormat")}>
          <Select value={format} onChange={(e) => setFormat(e.target.value)}>
            {formats.map((f) => <option key={f.name} value={f.name}>{f.name === "bank" ? t("formats.bank") : f.label}</option>)}
          </Select>
        </Field>
        <Field label={t("statementFile")} hint={fileName || t("csvOnly")}>
          <input ref={fileInput} type="file" accept=".csv,text/csv,text/plain" className="block w-full text-sm file:mr-3 file:rounded-lg file:border file:border-line file:bg-surface file:px-3 file:py-1.5 file:text-sm" onChange={(e) => void pick(e.target.files?.[0])} />
        </Field>
        {readError && <Alert tone="bad">{readError}</Alert>}
        {result && (
          <Alert tone={result.skipped.length ? "warn" : "ok"}>
            <p>{t("importResult", { created: result.created, duplicates: result.duplicates, skipped: result.skipped.length })}</p>
            {result.skipped.length > 0 && <ul className="mt-2 max-h-40 list-disc overflow-auto pl-5 text-xs">{result.skipped.map((s, i) => <li key={i}>{s}</li>)}</ul>}
          </Alert>
        )}
      </div>
    </Drawer>
  );
}
