import { useQuery } from "@tanstack/react-query";

import { Alert, ErrorState, PageHeader, Skeleton, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { useOperatorCan } from "../../me";
import { CapPanel } from "./CapPanel";
import { ProviderCard } from "./ProviderCard";
import { UsagePanel } from "./UsagePanel";

export const AI_KEY = ["operator", "ai"];

/** Platform > AI: the providers the assistant can use (keys, models, data terms), the default one, the spend cap and the use so far. */
export default function AiPage() {
  const { t } = useTranslation("operator");
  const allowed = useOperatorCan("platform.ai");
  const overview = useQuery({ queryKey: AI_KEY, enabled: allowed, queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/ai")) });
  if (!allowed) return <Alert tone="info">{t("ai.noAccess")}</Alert>;
  return (
    <div className="space-y-4">
      <PageHeader title={t("ai.title")} description={t("ai.description")} />
      {overview.isPending ? <Skeleton className="h-64 w-full" />
        : overview.isError ? <ErrorState title={t("ai.loadFailed")} message={overview.error.message} onRetry={() => void overview.refetch()} />
        : (
          <>
            {overview.data.default_provider === null && (
              <Alert tone="warn">{overview.data.environment_provider ? t("ai.fromEnvironment", { provider: overview.data.environment_provider }) : t("ai.noDefault")}</Alert>
            )}
            {overview.data.cap_reached && <Alert tone="bad">{t("ai.capReached")}</Alert>}
            {overview.data.production && <p className="text-xs text-muted">{t("ai.productionNote")}</p>}
            {overview.data.providers.map((p) => (
              <ProviderCard key={`${p.name}:${p.updated_at}:${p.live_models_at}:${p.last_tested_at}`} provider={p} overview={overview.data} onChanged={() => void overview.refetch()} />
            ))}
            <CapPanel overview={overview.data} onChanged={() => void overview.refetch()} />
            <UsagePanel />
          </>
        )}
    </div>
  );
}
