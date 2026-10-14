import { ShieldCheck } from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  api, Alert, Badge, BackupCodes, Button, Card, ErrorState, Field, Input, isAnyCode, Modal, normaliseAnyCode, SkeletonRows, toast, TwoStepSetup, unwrap,
  useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

type Dialog = "setup" | "off" | "codes" | null;

/** My account > Two-step verification: status, set up, switch off, and new backup codes. */
export default function TwoStepCard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [dialog, setDialog] = useState<Dialog>(null);
  const status = useQuery({ queryKey: ["mfa-status"], queryFn: () => unwrap(api.GET("/api/v1/auth/mfa")) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["mfa-status"] });
  const close = () => setDialog(null);

  const body = () => {
    if (status.error) return <ErrorState message={status.error.message} onRetry={() => void status.refetch()} />;
    if (!status.data) return <SkeletonRows rows={2} cols={2} />;
    const s = status.data;
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <ShieldCheck className={s.enabled ? "h-5 w-5 text-ok" : "h-5 w-5 text-muted"} />
          <Badge tone={s.enabled ? "ok" : "neutral"}>{t(s.enabled ? "mfa.card.on" : "mfa.card.off")}</Badge>
          {s.enabled && <span className="text-sm text-muted">{t("mfa.card.backupLeft", { count: s.backup_codes_left })}</span>}
        </div>
        {s.enabled && s.backup_codes_left <= 2 && <Alert tone="warn">{t("mfa.card.lowBackup")}</Alert>}
        {s.required ? <Alert tone="info">{t("mfa.card.requiredNote")}</Alert> : !s.enabled && <p className="text-sm text-muted">{t("mfa.card.policyNote")}</p>}
        <div className="flex flex-wrap gap-2">
          {!s.enabled && <Button onClick={() => setDialog("setup")}>{t("mfa.card.setUp")}</Button>}
          {s.enabled && <Button variant="secondary" onClick={() => setDialog("codes")}>{t("mfa.card.newCodes")}</Button>}
          {s.enabled && !s.required && <Button variant="secondary" onClick={() => setDialog("off")}>{t("mfa.card.switchOff")}</Button>}
        </div>
      </div>
    );
  };

  return (
    <Card title={t("mfa.card.title")} description={t("mfa.card.hint")}>
      {body()}
      <Modal open={dialog === "setup"} onClose={close} title={t("mfa.card.title")}>
        <TwoStepSetup onCancel={close} onFinished={() => { close(); void refresh(); toast(t("mfa.card.enabledDone"), "ok"); }} />
      </Modal>
      {dialog === "off" && <ConfirmWithCode title={t("mfa.card.offTitle")} hint={t("mfa.card.offHint")} danger onClose={close} onDone={() => { close(); void refresh(); toast(t("mfa.card.offDone"), "ok"); }} />}
      {dialog === "codes" && <ConfirmWithCode title={t("mfa.card.newCodesTitle")} hint={t("mfa.card.newCodesHint")} regenerate onClose={close} onDone={() => { void refresh(); }} />}
    </Card>
  );
}

/** Asks for the password and a current code, then switches off, or (regenerate) shows the new backup codes once. */
function ConfirmWithCode({ title, hint, danger, regenerate, onClose, onDone }: { title: string; hint: string; danger?: boolean; regenerate?: boolean; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation();
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const send = useMutation({
    meta: { silent: true },
    mutationFn: async () => {
      const body = { password, code: normaliseAnyCode(code) };
      if (regenerate) return (await unwrap(api.POST("/api/v1/auth/mfa/backup-codes", { body }))).backup_codes;
      await unwrap(api.POST("/api/v1/auth/mfa/disable", { body }));
      return null;
    },
    onSuccess: (result) => {
      if (result) { setCodes(result); onDone(); } else onDone();
    },
    onError: () => setCode(""),
  });
  const ready = password !== "" && isAnyCode(code);
  const submit = (e: FormEvent) => { e.preventDefault(); if (ready && !send.isPending) send.mutate(); };

  if (codes) {
    return <Modal open onClose={onClose} title={t("mfa.card.newCodesTitle")}><BackupCodes codes={codes} onDone={onClose} doneLabel={t("mfa.card.close")} /></Modal>;
  }
  return (
    <Modal open onClose={onClose} title={title} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("mfa.cancel")}</Button><Button type="submit" form="mfa-confirm" variant={danger ? "danger" : "primary"} loading={send.isPending} disabled={!ready}>{t(regenerate ? "mfa.card.getCodes" : "mfa.card.confirmOff")}</Button></>}>
      <form id="mfa-confirm" onSubmit={submit} className="space-y-4">
        <p className="text-sm text-muted">{hint}</p>
        <Field label={t("mfa.card.password")}><Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus /></Field>
        <Field label={t("mfa.card.code")} hint={code !== "" && !isAnyCode(code) ? t("mfa.card.badCode") : undefined}>
          <Input value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" autoCapitalize="none" spellCheck={false} className="font-mono" />
        </Field>
        {send.isError && <Alert tone="bad">{send.error.message}</Alert>}
      </form>
    </Modal>
  );
}
