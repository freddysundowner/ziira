import { type FormEvent, useState } from "react";

import { api, Badge, Button, Card, Field, Input, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

/** Step 1: the platform key from the Lead Intel account. It is checked with Lead Intel, stored encrypted and never shown again. */
export default function KeyCard({ companyId, saved }: { companyId: string; saved: boolean }) {
  const { t } = useTranslation("leadsintel");
  const qc = useQueryClient();
  const [editing, setEditing] = useState(!saved);
  const [key, setKey] = useState("");
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.PUT("/api/v1/plugins/leadsintel/key", { body: { company_id: companyId, platform_key: key.trim() } })),
    onSuccess: () => { setKey(""); setEditing(false); toast(t("keySaved"), "ok"); void qc.invalidateQueries({ queryKey: ["leadsintel-state"] }); },
    onError: (e) => toast(e.message, "bad"),
  });
  const check = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/plugins/leadsintel/check", { body: { company_id: companyId } })),
    onSuccess: (r) => toast(r.message, r.ok ? "ok" : "bad"),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Card title={t("keyTitle")} description={t("keyHint")} actions={saved ? <Badge tone="ok">{t("keyOk")}</Badge> : undefined}>
      {editing ? (
        <form onSubmit={submit} className="space-y-3">
          <Field label={t("keyLabel")} hint={t("keyWriteOnly")}>
            <Input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="li_platform_…" required />
          </Field>
          <div className="flex gap-2">
            <Button type="submit" loading={save.isPending} disabled={key.trim().length < 8}>{t("keySave")}</Button>
            {saved && <Button variant="ghost" onClick={() => setEditing(false)}>{t("cancel")}</Button>}
          </div>
        </form>
      ) : (
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setEditing(true)}>{t("keyReplace")}</Button>
          <Button variant="ghost" loading={check.isPending} onClick={() => check.mutate()}>{t("keyCheck")}</Button>
        </div>
      )}
    </Card>
  );
}
