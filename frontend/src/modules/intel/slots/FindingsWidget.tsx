import { Link } from "react-router-dom";

import { api, unwrap, useQuery, useTranslation } from "@/sdk";

import { SeverityBadge } from "../components/Badges";
import { usePlain } from "../usePlain";
import { type Band, bandOf } from "../plainWords";

/** Dashboard box: how many things need a look, how urgent, and the three that matter most. */
export default function FindingsWidget() {
  const { t } = useTranslation("intel");
  const plain = usePlain();
  const summary = useQuery({ queryKey: ["intel", "summary"], queryFn: () => unwrap(api.GET("/api/v1/intel/findings/summary")), refetchInterval: 120_000 });
  const top = useQuery({ queryKey: ["intel", "findings", "top3"], queryFn: () => unwrap(api.GET("/api/v1/intel/findings", { params: { query: { limit: 3 } } })), refetchInterval: 120_000 });
  const error = summary.error ?? top.error;
  if (error) return <p className="text-sm text-bad">{error.message} <button className="underline" onClick={() => { void summary.refetch(); void top.refetch(); }}>{t("retry")}</button></p>;
  if (!summary.data || !top.data) return <p className="text-sm text-muted">{t("loading")}</p>;
  if (summary.data.open === 0) return <Link to="/intelligence/things" className="block text-sm text-muted">{t("widgetNone")}</Link>;
  const byBand: Record<Band, number> = { urgent: 0, soon: 0, look: 0 };
  for (const [severity, n] of Object.entries(summary.data.by_severity)) byBand[bandOf(severity)] += n;
  const bands = (["urgent", "soon", "look"] as const).filter((b) => byBand[b] > 0);
  const stand = { urgent: "high", soon: "medium", look: "low" } as const;
  return (
    <div className="space-y-3">
      <Link to="/intelligence/things" className="block">
        <p className="tnum text-2xl font-semibold">{t("widgetOpen", { count: summary.data.open })}</p>
        <div className="mt-1 flex flex-wrap gap-2">
          {bands.map((b) => <span key={b} className="inline-flex items-center gap-1"><SeverityBadge severity={stand[b]} /><span className="tnum text-xs text-muted">{byBand[b]}</span></span>)}
        </div>
      </Link>
      <ul className="space-y-1.5">
        {top.data.map((f) => (
          <li key={f.id}>
            <Link to={`/intelligence/things/${f.id}`} className="flex items-start gap-2 text-sm hover:underline">
              <SeverityBadge severity={f.severity} /><span className="min-w-0 flex-1 truncate">{plain.check(f.check_code)?.title ?? f.summary}</span>{f.source === "connected" && <span className="shrink-0 text-xs text-muted">{t("source.connectedShort")}</span>}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
