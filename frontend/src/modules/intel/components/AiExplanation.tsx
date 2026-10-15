import { Link } from "react-router-dom";

import {
  api, Button, Card, formatDate, toast, unwrap, useCan, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";
import type { Schemas } from "@/sdk";

import { reasonKey } from "../logic";
import AiBadge from "./AiBadge";

type Finding = Schemas["FindingDetailOut"];

/**
 * The AI-written explanation of a finding, always labelled as such, with a way for managers to have it written again.
 * Hidden when there is none and the assistant cannot write one.
 */
export default function AiExplanation({ finding }: { finding: Finding }) {
  const { t, i18n } = useTranslation("intel");
  const qc = useQueryClient();
  const canManage = useCan("findings.manage");
  const canSettings = useCan("ai.manage");
  const companyId = finding.company_id;
  const status = useQuery({
    enabled: canManage && !!companyId,
    queryKey: ["intel", "ai-status", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/intel/ai/status", { params: { query: { company_id: companyId! } } })),
  });
  const write = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/intel/findings/{finding_id}/ai-explanation", {
      params: { path: { finding_id: finding.id } }, body: { language: i18n.language === "sw" ? "sw" : "en" } })),
    onSuccess: (data) => { qc.setQueryData(["intel", "finding", finding.id], data); toast(t("ai.written"), "ok"); },
  });

  const available = status.data?.explanations_available === true;
  if (!finding.explanation_ai && !(canManage && available)) {
    return canManage && status.data && canSettings && status.data.reason
      ? <p className="text-xs text-muted">{t(`ai.unavailable.${reasonKey(status.data.reason)}`)} <Link className="underline" to="/admin/settings?tab=ai">{t("ai.openSettings")}</Link></p>
      : null;
  }
  return (
    <Card title={<span className="inline-flex flex-wrap items-center gap-2">{t("ai.explanationTitle")}<AiBadge /></span>} description={t("ai.explanationHint")}
      actions={canManage && available && (
        <Button size="sm" variant="secondary" loading={write.isPending} onClick={() => write.mutate()}>
          {finding.explanation_ai ? t("ai.regenerate") : t("ai.write")}
        </Button>
      )}>
      {finding.explanation_ai ? (
        <>
          <p className="whitespace-pre-wrap text-sm">{finding.explanation_ai}</p>
          {finding.explanation_ai_at && <p className="mt-2 text-xs text-muted">{formatDate(finding.explanation_ai_at, true)}</p>}
        </>
      ) : (
        <p className="text-sm text-muted">{t("ai.none")}</p>
      )}
    </Card>
  );
}
