import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Button, Card, ErrorState, Field, Input, type Schemas, Skeleton, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { usd } from "../../helpers/ai";
import { useOperatorCan } from "../../me";
import { useChange } from "../../stepUp";

const KEY = ["operator", "site-assistant"];
const AREA = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm";

/** The website assistant: the switch, its own monthly cap, the limits per visitor, and what the chat says first. Small and calm. */
export function SiteAssistantCard() {
  const { t } = useTranslation("operator");
  const settings = useQuery({ queryKey: KEY, queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/site-assistant")) });
  if (settings.isPending) return <Skeleton className="h-48 w-full" />;
  if (settings.isError) return <ErrorState title={t("ai.site.loadFailed")} message={settings.error.message} onRetry={() => void settings.refetch()} />;
  return <Form key={JSON.stringify(settings.data)} data={settings.data} onSaved={() => void settings.refetch()} />;
}

function Form({ data, onSaved }: { data: Schemas["SiteAssistantOut"]; onSaved: () => void }) {
  const { t } = useTranslation("operator");
  const editable = useOperatorCan("platform.ai");
  const [enabled, setEnabled] = useState(data.enabled);
  const [cap, setCap] = useState(data.monthly_cap_usd ?? "");
  const [perMinute, setPerMinute] = useState(String(data.per_minute));
  const [perDay, setPerDay] = useState(String(data.per_day));
  const [total, setTotal] = useState(String(data.daily_total));
  const [greeting, setGreeting] = useState(data.greeting);
  const [chips, setChips] = useState(data.suggestions.join("\n"));
  const [problem, setProblem] = useState<string | null>(null);
  const save = useChange(() => opUnwrap(opApi.PUT("/api/v1/operator/site-assistant", { body: {
    enabled, monthly_cap_usd: cap.trim() === "" ? null : cap.trim(), per_minute: Number(perMinute), per_day: Number(perDay), daily_total: Number(total),
    greeting: greeting.trim(), suggestions: chips.split("\n").map((x) => x.trim()).filter(Boolean),
  } })), { onSuccess: () => { toast(t("ai.site.saved"), "ok"); onSaved(); }, onError: (e) => setProblem(e.message) });
  const status = data.available ? <Alert tone="ok">{t("ai.site.on")}</Alert>
    : enabled && data.blocked_reason === "budget" ? <Alert tone="warn">{t("ai.site.budget")}</Alert>
    : <Alert tone="info">{data.enabled ? t("ai.site.noProvider") : t("ai.site.off")}</Alert>;
  return (
    <Card title={t("ai.site.title")} description={t("ai.site.description")}>
      <form className="space-y-4" noValidate onSubmit={(e) => { e.preventDefault(); setProblem(null); save.mutate(undefined); }}>
        {status}
        <fieldset disabled={!editable || save.isPending} className="grid min-w-0 gap-4 min-[900px]:grid-cols-2">
          <label className="flex items-center gap-2 text-sm min-[900px]:col-span-2">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            {t("ai.site.enable")}
          </label>
          <Field label={t("ai.site.cap")} hint={t("ai.site.capHint", { spent: usd(data.month_spend_usd) })}>
            <Input inputMode="decimal" value={cap} placeholder={t("ai.site.noCap")} onChange={(e) => setCap(e.target.value)} />
          </Field>
          <Field label={t("ai.site.perMinute")} hint={t("ai.site.perMinuteHint")}>
            <Input inputMode="numeric" value={perMinute} onChange={(e) => setPerMinute(e.target.value)} />
          </Field>
          <Field label={t("ai.site.perDay")} hint={t("ai.site.perDayHint")}>
            <Input inputMode="numeric" value={perDay} onChange={(e) => setPerDay(e.target.value)} />
          </Field>
          <Field label={t("ai.site.total")} hint={t("ai.site.totalHint")}>
            <Input inputMode="numeric" value={total} onChange={(e) => setTotal(e.target.value)} />
          </Field>
          <Field className="min-[900px]:col-span-2" label={t("ai.site.greeting")}>
            <textarea className={AREA} rows={2} maxLength={300} value={greeting} onChange={(e) => setGreeting(e.target.value)} />
          </Field>
          <Field className="min-[900px]:col-span-2" label={t("ai.site.chips")} hint={t("ai.site.chipsHint")}>
            <textarea className={AREA} rows={4} value={chips} onChange={(e) => setChips(e.target.value)} />
          </Field>
        </fieldset>
        {problem && <Alert tone="bad">{problem}</Alert>}
        <p className="text-xs text-muted">{t("ai.site.usage", { calls: data.usage.calls, cost: usd(data.usage.cost_usd) })}</p>
        {editable && <Button type="submit" disabled={save.isPending}>{t("ai.save")}</Button>}
      </form>
    </Card>
  );
}
