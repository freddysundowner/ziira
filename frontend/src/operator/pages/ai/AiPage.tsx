import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Alert, Card, ErrorState, Field, PageHeader, Select, Skeleton, useDisclosure, useTranslation, useUnsavedWarning } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { type AiOverview, NO_PROVIDER, providerDirty, providerDraft, statusOf } from "../../helpers/ai";
import { useOperatorCan } from "../../me";
import { NoProvider } from "./NoProvider";
import { type FormState, ProviderForm } from "./ProviderForm";
import { ProviderCard } from "./ProviderCard";
import { SiteAssistantCard } from "./SiteAssistantCard";
import { UsagePanel } from "./UsagePanel";

export const AI_KEY = ["operator", "ai"];

/** Platform > AI: one dropdown picks the provider in use; its key, model and spend limit are the only fields. The rest is under Details. */
export default function AiPage() {
  const { t } = useTranslation("operator");
  const allowed = useOperatorCan("platform.ai");
  const overview = useQuery({ queryKey: AI_KEY, enabled: allowed, queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/ai")) });
  if (!allowed) return <Alert tone="info">{t("ai.noAccess")}</Alert>;
  return (
    <div className="space-y-4">
      <PageHeader title={t("ai.title")} description={t("ai.formDescription")} />
      {overview.isPending ? <Skeleton className="h-64 w-full" />
        : overview.isError ? <ErrorState title={t("ai.loadFailed")} message={overview.error.message} onRetry={() => void overview.refetch()} />
        : <Loaded overview={overview.data} onChanged={() => void overview.refetch()} />}
    </div>
  );
}

function Loaded({ overview, onChanged }: { overview: AiOverview; onChanged: () => void }) {
  const { t } = useTranslation("operator");
  const details = useDisclosure(false);
  const canAudit = useOperatorCan("platform.operators");
  const [selected, setSelected] = useState<string>(overview.default_provider ?? NO_PROVIDER);
  const [forms, setForms] = useState<Record<string, FormState>>({});
  const provider = overview.providers.find((x) => x.name === selected);
  const current: FormState | null = provider ? (forms[provider.name] ?? { draft: providerDraft(provider), typingOther: false, replacingKey: false, cap: overview.monthly_cap_usd ?? "" }) : null;
  useUnsavedWarning(!!provider && !!current && (providerDirty(provider, { ...current.draft, enabled: true }) || current.cap.trim() !== (overview.monthly_cap_usd ?? "")));
  const status = statusOf(overview);
  const kept = overview.providers.filter((x) => x.key_set && x.name !== selected);
  const statusNode = (
    status.on ? <Alert tone="ok">{t("ai.status.on", { provider: status.provider, model: status.model })}</Alert>
        : <Alert tone={overview.environment_provider ? "info" : "warn"}>{overview.environment_provider ? t("ai.fromEnvironment", { provider: overview.environment_provider }) : t("ai.status.off")}</Alert>
  );
  const providerField = (
    <Field label={t("ai.form.provider")} hint={t("ai.form.providerHint")}>
      <Select value={selected} onChange={(e) => setSelected(e.target.value)}>
        {overview.providers.map((p) => <option key={p.name} value={p.name}>{p.title}</option>)}
        <option value={NO_PROVIDER}>{t("ai.form.none")}</option>
      </Select>
    </Field>
  );
  return (
    <>
      {overview.cap_reached && <Alert tone="bad">{t("ai.capReached")}</Alert>}
      <Card>
        <div className="space-y-4">
          {kept.length > 0 && <p className="text-xs text-muted">{kept.map((o) => t("ai.form.otherKeptUnused", { name: o.title })).join(" ")}</p>}
          {provider && current
            ? <ProviderForm provider={provider} overview={overview} state={current}
                setState={(next) => setForms({ ...forms, [provider.name]: next })} onChanged={onChanged} providerField={providerField} status={statusNode}
                onSaved={() => { setForms((f) => Object.fromEntries(Object.entries(f).filter(([k]) => k !== provider.name))); onChanged(); }} />
            : <NoProvider overview={overview} onChanged={onChanged} providerField={providerField} status={statusNode} />}
        </div>
      </Card>
      <section>
        <button type="button" aria-expanded={details.open} aria-controls="ai-details" onClick={details.toggle}
          className="flex w-full items-center justify-between rounded-lg border border-line bg-surface px-4 py-3 text-left text-sm font-semibold hover:bg-sunken">
          <span>{t("ai.details.title")}<span className="ml-2 text-xs font-normal text-muted">{t("ai.details.hint")}</span></span>
          <span aria-hidden>{details.open ? "−" : "+"}</span>
        </button>
        {details.open && (
          <div id="ai-details" className="mt-3 space-y-4">
            <UsagePanel />
            <SiteAssistantCard />
            <h2 className="pt-2 text-sm font-semibold">{t("ai.details.providers")}</h2>
            <p className="-mt-3 text-xs text-muted">{t("ai.details.providersHint")}</p>
            {overview.providers.map((p) => (
              <ProviderCard key={`${p.name}:${p.updated_at}:${p.live_models_at}:${p.last_tested_at}`} provider={p} overview={overview} onChanged={onChanged} />
            ))}
            {overview.production && <p className="text-xs text-muted">{t("ai.productionNote")}</p>}
            {canAudit && <p className="text-sm"><Link className="underline" to={"/operator/audit"}>{t("ai.details.audit")}</Link></p>}
          </div>
        )}
      </section>
    </>
  );
}
