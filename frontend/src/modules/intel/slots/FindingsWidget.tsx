import { Link } from "react-router-dom";

import { api, unwrap, useQuery, useTranslation } from "@/sdk";

import { SeverityBadge } from "../components/Badges";
import { SEVERITIES } from "../logic";

/** Dashboard box: open findings by severity, and the three that matter most. */
export default function FindingsWidget() {
  const { t } = useTranslation("intel");
  const summary = useQuery({ queryKey: ["intel", "summary"], queryFn: () => unwrap(api.GET("/api/v1/intel/findings/summary")), refetchInterval: 120_000 });
  const top = useQuery({ queryKey: ["intel", "findings", "top3"], queryFn: () => unwrap(api.GET("/api/v1/intel/findings", { params: { query: { limit: 3 } } })), refetchInterval: 120_000 });
  const error = summary.error ?? top.error;
  if (error) return <p className="text-sm text-bad">{error.message} <button className="underline" onClick={() => { void summary.refetch(); void top.refetch(); }}>{t("retry")}</button></p>;
  if (!summary.data || !top.data) return <p className="text-sm text-muted">{t("loading")}</p>;
  if (summary.data.open === 0) return <Link to="/findings" className="block text-sm text-muted">{t("widgetNone")}</Link>;
  const bySeverity = summary.data.by_severity;
  const known: readonly string[] = SEVERITIES;
  const severities = [...SEVERITIES, ...Object.keys(bySeverity).filter((s) => !known.includes(s))].filter((s) => (bySeverity[s] ?? 0) > 0);
  return (
    <div className="space-y-3">
      <Link to="/findings" className="block">
        <p className="tnum text-2xl font-semibold">{t("widgetOpen", { count: summary.data.open })}</p>
        <div className="mt-1 flex flex-wrap gap-2">
          {severities.map((s) => <span key={s} className="inline-flex items-center gap-1"><SeverityBadge severity={s} /><span className="tnum text-xs text-muted">{bySeverity[s]}</span></span>)}
        </div>
      </Link>
      <ul className="space-y-1.5">
        {top.data.map((f) => (
          <li key={f.id}>
            <Link to={`/findings/${f.id}`} className="flex items-start gap-2 text-sm hover:underline">
              <SeverityBadge severity={f.severity} /><span className="min-w-0 flex-1 truncate">{f.summary}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
