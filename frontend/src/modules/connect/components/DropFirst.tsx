import { useState } from "react";

import { Alert, api, Button, Card, Field, Input, type Schemas, unwrap, useMutation, useTranslation } from "@/sdk";

import { DropZone } from "./DropZone";

type Kind = Schemas["ConnectorKindOut"];

/** The quickest start: drop any file and we say what it is (a bank statement, a sales export ...) and carry on. */
export function DropFirst({ kinds, onFound }: { kinds: readonly Kind[]; onFound: (kind: Kind, file: File, password: string) => void }) {
  const { t } = useTranslation("connect");
  const [file, setFile] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const detect = useMutation({
    meta: { silent: true },
    mutationFn: (v: { file: File; password: string }) => unwrap(api.POST("/api/v1/connect/files/detect", {
      body: v.file as unknown as string,
      bodySerializer: (body) => body as BodyInit,
      headers: { "Content-Type": "application/octet-stream", ...(v.password ? { "X-File-Password": v.password } : {}) },
    })),
    onSuccess: (r, v) => {
      const kind = kinds.find((k) => k.kind === r.kind);
      if (kind) onFound(kind, v.file, v.password);
    },
  });
  const go = (f: File, pw = "") => { setFile(f); detect.mutate({ file: f, password: pw }); };
  const answer = detect.data;
  const lost = answer && answer.state === "ready" && !kinds.some((k) => k.kind === answer.kind);
  return (
    <Card title={t("wizard.dropFirst")} description={t("wizard.dropFirstHint")}>
      <div className="space-y-3">
        <DropZone onFile={go} busy={detect.isPending} statement />
        {detect.isPending && <p className="text-sm text-muted" role="status">{t("upload.checking")}</p>}
        {answer && (answer.state === "password_required" || answer.state === "wrong_password") && file && (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); go(file, password); }}>
            <Alert tone={answer.state === "wrong_password" ? "bad" : "info"}>{answer.message}</Alert>
            <Field label={t("upload.password")} hint={t("upload.passwordHint")}><Input type="password" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} required /></Field>
            <Button type="submit" disabled={!password}>{t("upload.openFile")}</Button>
          </form>
        )}
        {lost && <Alert tone="warn">{t("wizard.notSure")}</Alert>}
        {detect.error && <Alert tone="bad">{detect.error.message}</Alert>}
      </div>
    </Card>
  );
}
