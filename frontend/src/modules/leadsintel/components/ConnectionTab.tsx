import { api, Alert, Badge, Button, Card, ErrorState, SkeletonRows, unwrap, useQuery, useTranslation } from "@/sdk";

import { currentStep } from "../logic";
import ConnectedCard from "./ConnectedCard";
import KeyCard from "./KeyCard";
import NumberCard from "./NumberCard";

/** The Lead Intel connection wizard: 1 the platform key, 2 the WhatsApp number, 3 connected (test, disconnect). */
export default function ConnectionTab({ companyId }: { companyId: string }) {
  const { t } = useTranslation("leadsintel");
  const state = useQuery({
    queryKey: ["leadsintel-state", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/plugins/leadsintel/state", { params: { query: { company_id: companyId } } })),
  });
  if (state.error) return <ErrorState message={state.error.message} onRetry={() => void state.refetch()} />;
  if (!state.data) return <SkeletonRows rows={3} cols={2} />;
  const data = state.data;
  const step = currentStep(data.key_saved, data.whatsapp?.status);
  return (
    <div className="space-y-4">
      <Alert tone="warn">{t("untestedNote")}</Alert>
      <ol className="flex flex-wrap gap-2 text-xs">
        {([1, 2, 3] as const).map((n) => (
          <li key={n}><Badge tone={n < step ? "ok" : n === step ? "info" : "neutral"}>{n}. {t(`step${n}`)}</Badge></li>
        ))}
      </ol>
      <KeyCard companyId={companyId} saved={data.key_saved} />
      {data.key_saved && (step === 3
        ? <ConnectedCard companyId={companyId} state={data} />
        : <NumberCard companyId={companyId} state={data} />)}
      {state.isFetching && <span className="sr-only">{t("refreshing")}</span>}
      <Card><Button variant="ghost" size="sm" onClick={() => void state.refetch()}>{t("refresh")}</Button></Card>
    </div>
  );
}
