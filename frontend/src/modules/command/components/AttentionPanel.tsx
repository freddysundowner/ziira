import { Link } from "react-router-dom";

import { Badge, Card, humanise, money, useCan, useTranslation } from "@/sdk";
import type { Schemas } from "@/sdk";

import { severityCounts } from "../logic";
import Severity from "./Severity";

type Overview = Schemas["OverviewOut"];

/** The findings that need the user: counts by severity and the top few, each linking to its page. */
export default function AttentionPanel({ overview }: { overview: Overview }) {
  const { t } = useTranslation("command");
  const canOpen = useCan("findings.view");
  const counts = severityCounts(overview.findings_by_severity);
  return (
    <Card title={t("attention")} description={t("attentionHint")}
      actions={canOpen && <Link className="text-sm font-medium text-brand hover:underline" to="/findings">{t("allFindings")}</Link>}>
      {overview.top_findings.length === 0 ? (
        <p className="text-sm text-muted">{t("noAttention")}</p>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">{t("openCount", { count: overview.open_findings })}</span>
            {counts.map((c) => <span key={c.severity} className="inline-flex items-center gap-1"><Severity severity={c.severity} /><span className="tnum text-xs text-muted">{c.count}</span></span>)}
          </div>
          <ul className="divide-y divide-line">
            {overview.top_findings.map((f) => {
              const body = (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <Severity severity={f.severity} />
                    {f.area && <Badge>{t(`area.${f.area}`, humanise(f.area))}</Badge>}
                    {f.amount && <span className="tnum text-xs text-muted">{t("amountInvolved", { amount: money(f.amount, overview.currency) })}</span>}
                  </div>
                  <p className="mt-1 text-sm font-medium">{f.summary}</p>
                  {f.recommended_action && <p className="mt-0.5 text-sm text-muted">{t("nextStep", { action: f.recommended_action })}</p>}
                </>
              );
              return (
                <li key={f.id} className="py-3 first:pt-0 last:pb-0">
                  {canOpen ? <Link to={`/findings/${f.id}`} className="block rounded-lg hover:bg-sunken/60">{body}</Link> : body}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </Card>
  );
}
