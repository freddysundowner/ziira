import { useState } from "react";

import { Alert, Badge, Button, Card, Field, Input, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { useChange } from "../../stepUp";
import type { ChatOverview } from "./logic";

/** Step 1: the provider's key. Write-only: it shows "Saved" or "Not set", never the key or any part of it. */
export function KeyCard({ overview: o, editable, onChanged }: { overview: ChatOverview; editable: boolean; onChanged: () => void }) {
  const { t } = useTranslation("operator");
  const [key, setKey] = useState("");
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const saveAndTest = useChange(
    async (value: string) => {
      if (value.trim()) await opUnwrap(opApi.PUT("/api/v1/operator/chat/key", { body: { api_key: value.trim() } }));
      return opUnwrap(opApi.POST("/api/v1/operator/chat/key/test"));
    },
    {
      onSuccess: (r) => { setResult(r); setKey(""); setProblem(null); onChanged(); },
      onError: (e) => { setProblem(e.message); onChanged(); },
    },
  );
  const tested = o.key.tested_ok;
  return (
    <Card title={t("chat.key.title")} description={t("chat.key.intro")}
      actions={<Badge tone={!o.key.is_set ? "neutral" : tested ? "ok" : tested === false ? "bad" : "warn"}>
        {!o.key.is_set ? t("chat.key.notSet") : tested ? t("chat.key.savedOk") : tested === false ? t("chat.key.savedBad") : t("chat.key.saved")}
      </Badge>}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (editable && !saveAndTest.isPending && (key.trim() || o.key.is_set)) { setResult(null); saveAndTest.mutate(key); } }}>
        <fieldset disabled={!editable}>
          <Field label={o.provider?.fields[0]?.label ?? t("chat.key.label")} hint={t("chat.key.hint")}>
            <Input type="password" autoComplete="off" value={key} onChange={(e) => { setKey(e.target.value); setResult(null); setProblem(null); }}
              placeholder={o.key.is_set ? t("chat.key.keep") : t("chat.key.paste")} />
          </Field>
        </fieldset>
        {result && <Alert tone={result.ok ? "ok" : "bad"}>{result.ok ? t("chat.key.accepted") : result.message}</Alert>}
        {problem && <Alert tone="bad">{problem}</Alert>}
        {editable && (
          <div className="flex justify-end">
            <Button type="submit" size="sm" loading={saveAndTest.isPending} disabled={!key.trim() && !o.key.is_set}>{t("chat.key.saveAndTest")}</Button>
          </div>
        )}
      </form>
    </Card>
  );
}
