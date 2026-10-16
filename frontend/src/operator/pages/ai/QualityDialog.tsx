import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, Modal, Skeleton, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { usd } from "../../helpers/ai";
import { useChange } from "../../stepUp";

/** The quality check: five questions in English and Swahili against a made-up business. Real calls, so the estimated cost is shown and must be confirmed. */
export function QualityDialog({ provider, model, onClose }: { provider: string; model: string; onClose: () => void }) {
  const { t } = useTranslation("operator");
  const [agreed, setAgreed] = useState(false);
  const estimate = useQuery({ queryKey: ["operator", "ai", "quality", provider, model], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/ai/quality-check/estimate", { params: { query: { provider, level: "quick", model } } })) });
  const run = useChange(() => opUnwrap(opApi.POST("/api/v1/operator/ai/quality-check", { body: { provider, model, level: "quick", confirm_cost: true } })));
  const report = run.data;
  return (
    <Modal open onClose={onClose} title={t("ai.quality.title")} size="lg"
      footer={<><Button variant="secondary" onClick={onClose}>{t("ai.close")}</Button>
        {!report && <Button loading={run.isPending} disabled={!agreed || estimate.isPending} onClick={() => run.mutate(undefined)}>{t("ai.quality.run")}</Button>}</>}>
      <div className="space-y-3">
        <p className="text-sm text-muted">{t("ai.quality.intro", { model })}</p>
        {!report && (estimate.isPending ? <Skeleton className="h-12 w-full" /> : estimate.isError ? <Alert tone="bad">{estimate.error.message}</Alert> : (
          <>
            <Alert tone="warn">{t("ai.quality.cost", { questions: estimate.data.questions, cost: usd(estimate.data.estimated_cost_usd) })}{!estimate.data.price_known && ` ${t("ai.quality.noPrice")}`}</Alert>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />{t("ai.quality.agree")}</label>
          </>
        ))}
        {run.isError && <Alert tone="bad">{run.error.message}</Alert>}
        {report && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={report.verdict === "good" ? "ok" : report.verdict === "acceptable" ? "warn" : "bad"}>{t(`ai.quality.verdict.${report.verdict}`)}</Badge>
              <span className="text-sm font-semibold">{t("ai.quality.score", { score: report.score })}</span>
              <span className="text-xs text-muted">{t("ai.quality.facts", { ms: report.latency_ms_average, tokens: report.tokens_in + report.tokens_out, cost: usd(report.cost_usd) })}</span>
            </div>
            <ul className="space-y-2">
              {report.questions.map((q) => {
                const checks = q.checks as { name: string; passed: boolean; detail: string }[];
                return (
                  <li key={String(q.id)} className="rounded border border-line p-2 text-sm">
                    <p className="font-medium">{String(q.question)}</p>
                    <p className="text-xs text-muted">{checks.map((c) => `${c.passed ? "✓" : "✗"} ${t(`ai.quality.check.${c.name}`)}${c.detail ? ` (${c.detail})` : ""}`).join("  ·  ")}</p>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>
    </Modal>
  );
}
