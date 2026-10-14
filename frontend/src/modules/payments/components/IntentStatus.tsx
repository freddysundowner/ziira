import { CheckCircle2, Clock, XCircle } from "lucide-react";

import { useEffect } from "react";

import { api, Button, formatDate, Spinner, unwrap, useQuery, useQueryClient, useTranslation } from "@/sdk";

import { isFinalIntent } from "../logic";
import { Amount } from "./Amount";
import { useAutoRefresh } from "./useAutoRefresh";

/** One payment prompt, asking the server every few seconds until it ends (paid, failed, cancelled or timed out). */
export function IntentStatus({ intentId, companyId }: { intentId: string; companyId?: string }) {
  const { t } = useTranslation("payments");
  const q = useQuery({
    queryKey: ["payment-intent", intentId],
    queryFn: () => unwrap(api.GET("/api/v1/payments/intents/{intent_id}", { params: { path: { intent_id: intentId } } })),
  });
  const qc = useQueryClient();
  const intent = q.data;
  const pending = !!intent && !isFinalIntent(intent.status);
  const final = intent && !pending ? intent.status : null;
  useEffect(() => {
    if (!final) return;
    void qc.invalidateQueries({ queryKey: ["payment-intents"] });
    if (final === "succeeded") void qc.invalidateQueries({ queryKey: ["payments"] });
  }, [final, qc]);
  useAutoRefresh(pending, () => void q.refetch(), 3000);

  if (q.error && !intent) return <p className="text-sm text-bad">{q.error.message} <Button size="sm" variant="ghost" onClick={() => void q.refetch()}>{t("retry")}</Button></p>;
  if (!intent) return <div className="flex items-center gap-2 text-sm text-muted"><Spinner />{t("loading")}</div>;

  const Icon = intent.status === "succeeded" ? CheckCircle2 : pending ? Clock : XCircle;
  const tone = intent.status === "succeeded" ? "text-ok" : pending ? "text-warn" : "text-bad";
  return (
    <div className="space-y-3 text-center" role="status" aria-live="polite">
      <Icon className={`mx-auto h-12 w-12 ${tone}`} />
      <p className="tnum text-2xl font-semibold"><Amount value={intent.amount} companyId={companyId} /></p>
      <p className="text-sm font-medium">{t(`intentTitles.${intent.status}`, intent.status)}</p>
      <p className="text-sm text-muted">{t(`intentHints.${intent.status}`, "")}</p>
      {pending && <div className="flex items-center justify-center gap-2 text-xs text-muted"><Spinner />{t("checkingEvery")}</div>}
      <dl className="mx-auto grid max-w-xs grid-cols-2 gap-x-4 gap-y-1 text-left text-sm">
        <dt className="text-muted">{t("phone")}</dt><dd className="tnum">{intent.phone_masked}</dd>
        {intent.receipt && (<><dt className="text-muted">{t("receipt")}</dt><dd className="font-mono text-xs">{intent.receipt}</dd></>)}
        {intent.expires_at && pending && (<><dt className="text-muted">{t("expires")}</dt><dd>{formatDate(intent.expires_at, true)}</dd></>)}
        {intent.result_code && !pending && intent.status !== "succeeded" && (<><dt className="text-muted">{t("resultCode")}</dt><dd className="font-mono text-xs">{intent.result_code}</dd></>)}
      </dl>
    </div>
  );
}
