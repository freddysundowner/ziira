import { useEffect, useState } from "react";

import { api, Alert, Button, Card, ConfirmDialog, ErrorState, Field, Select, SkeletonRows, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

const POLICIES = ["off", "privileged", "everyone"] as const;
type Policy = (typeof POLICIES)[number];
const KEY = ["security-settings"];

/** Who must sign in with a second factor. */
export default function SecurityTab() {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: KEY, queryFn: () => unwrap(api.GET("/api/v1/settings/security")) });
  const [policy, setPolicy] = useState<Policy>("off");
  const [asking, setAsking] = useState(false);
  useEffect(() => {
    if (settings.data) setPolicy(POLICIES.find((p) => p === settings.data.mfa_policy) ?? "off");
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () => unwrap(api.PATCH("/api/v1/settings/security", { body: { mfa_policy: policy } })),
    onSuccess: (data) => { qc.setQueryData(KEY, data); setAsking(false); toast(t("securitySaved"), "ok"); },
    onSettled: () => setAsking(false),
  });

  if (settings.error) return <ErrorState message={settings.error.message} onRetry={() => void settings.refetch()} />;
  if (!settings.data) return <SkeletonRows rows={3} cols={2} />;

  const changed = policy !== settings.data.mfa_policy;
  const onSave = () => (policy === "off" ? save.mutate() : setAsking(true));
  return (
    <Card title={t("securityTitle")} description={t("securityHint")} className="max-w-2xl">
      <div className="space-y-4">
        <Field label={t("mfaRequiredFor")} hint={t(`mfaPolicyHelp.${policy}`)}>
          <Select value={policy} onChange={(e) => setPolicy(e.target.value as Policy)}>
            {POLICIES.map((p) => <option key={p} value={p}>{t(`mfaPolicy.${p}`)}</option>)}
          </Select>
        </Field>
        {policy !== "off" && changed && <Alert tone="warn">{t("mfaPolicyWarn")}</Alert>}
        <Button loading={save.isPending} disabled={!changed} onClick={onSave}>{t("securitySave")}</Button>
      </div>
      <ConfirmDialog open={asking} onClose={() => setAsking(false)} busy={save.isPending} danger title={t("securityConfirmTitle")} confirmLabel={t("securitySave")}
        message={<div className="space-y-2"><p>{t("mfaPolicyConfirm", { who: t(`mfaPolicy.${policy}`) })}</p><p>{t("mfaPolicyWarn")}</p></div>}
        onConfirm={() => save.mutate()} />
    </Card>
  );
}
