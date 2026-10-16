import { useState } from "react";

import { Alert, Button, Card, Field, Input, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { type AiOverview, usd } from "../../helpers/ai";
import { useChange } from "../../stepUp";

/** The platform-wide monthly spend cap, in US dollars (an estimate from token counts and the price table). */
export function CapPanel({ overview, onChanged }: { overview: AiOverview; onChanged: () => void }) {
  const { t } = useTranslation("operator");
  const [value, setValue] = useState(overview.monthly_cap_usd ?? "");
  const [problem, setProblem] = useState<string | null>(null);
  const save = useChange(() => opUnwrap(opApi.PUT("/api/v1/operator/ai/cap", { body: { cap_usd: value.trim() === "" ? null : value.trim() } })), {
    onSuccess: () => { toast(t("ai.cap.saved"), "ok"); onChanged(); },
    onError: (e) => setProblem(e.message),
  });
  const dirty = value.trim() !== (overview.monthly_cap_usd ?? "");
  return (
    <Card title={t("ai.cap.title")} description={t("ai.cap.hint")}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (dirty && !save.isPending) { setProblem(null); save.mutate(undefined); } }}>
        <p className="text-sm">{t("ai.cap.spent", { spend: usd(overview.month_spend_usd), cap: overview.monthly_cap_usd ? usd(overview.monthly_cap_usd) : t("ai.cap.none") })}</p>
        <Field label={t("ai.cap.label")} hint={t("ai.cap.labelHint")}>
          <Input inputMode="decimal" value={value} maxLength={20} onChange={(e) => { setValue(e.target.value); setProblem(null); }} />
        </Field>
        {problem && <Alert tone="bad">{problem}</Alert>}
        <div className="flex justify-end"><Button type="submit" size="sm" loading={save.isPending} disabled={!dirty}>{t("ai.save")}</Button></div>
      </form>
    </Card>
  );
}
