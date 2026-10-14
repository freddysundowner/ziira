import { Link } from "react-router-dom";

import { api, unwrap, useQuery, useTranslation } from "@/sdk";

import { formatFigure } from "../components/FigureCard";
import { changeOf, keyFigure } from "../logic";

const TONE = { ok: "text-ok", bad: "text-bad", neutral: "text-muted" } as const;

/** Dashboard box: today's key figure (the first company-wide money figure) against yesterday. */
export default function TodayWidget() {
  const { t } = useTranslation("command");
  const q = useQuery({ queryKey: ["command", "overview", "widget"], queryFn: () => unwrap(api.GET("/api/v1/command/overview", {})), refetchInterval: 120_000 });
  if (q.error) return <p className="text-sm text-bad">{q.error.message} <button className="underline" onClick={() => void q.refetch()}>{t("retry")}</button></p>;
  if (!q.data) return <p className="text-sm text-muted">{t("loading")}</p>;
  const fig = keyFigure(q.data.figures);
  if (!fig) return <Link to="/command" className="block text-sm text-muted">{t("widgetEmpty")}</Link>;
  const c = changeOf(fig.value, fig.previous, fig.higher_is_better);
  return (
    <Link to="/command" className="block space-y-1">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{fig.label}</p>
      <p className="tnum text-2xl font-semibold">{formatFigure(fig, fig.value, q.data.currency)}</p>
      <p className={`text-sm ${TONE[c.tone]}`}>
        {c.direction === "none" ? t("noYesterday") : c.direction === "flat" ? t("unchanged") : c.percent === null ? t("newToday") : t("vsYesterday", { percent: `${c.percent > 0 ? "+" : ""}${Math.round(c.percent * 10) / 10}` })}
      </p>
    </Link>
  );
}
