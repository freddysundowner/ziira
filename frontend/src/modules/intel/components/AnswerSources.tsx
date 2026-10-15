import { Fragment } from "react";

import { cx, humanise, useTranslation } from "@/sdk";

import { type AskSource, cellText, isNumeric, sourceColumns, sourcePeriod } from "../logic";

/** "Based on: …": the queries behind an answer, each expandable to the rows it returned. */
export default function AnswerSources({ sources }: { sources: readonly AskSource[] }) {
  const { t } = useTranslation("intel");
  if (sources.length === 0) return <p className="mt-2 text-xs text-muted">{t("ai.noSources")}</p>;
  return (
    <div className="mt-3 space-y-1">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t("ai.basedOn")}</p>
      {sources.map((s, i) => <Source key={`${s.tool}-${i}`} source={s} />)}
    </div>
  );
}

function Source({ source }: { source: AskSource }) {
  const { t } = useTranslation("intel");
  const columns = sourceColumns(source.rows);
  const right = (c: string) => source.rows.every((r) => r[c] == null || isNumeric(r[c]));
  const period = sourcePeriod(source);
  const extras = Object.entries(source.summary).filter(([k, v]) => k !== "note" && k !== "truncated" && (typeof v === "string" || typeof v === "number"));
  const note = typeof source.summary.note === "string" ? source.summary.note : null;
  return (
    <details className="rounded-lg border border-line bg-surface">
      <summary className="cursor-pointer px-3 py-2 text-sm">
        <span className="font-medium">{t(`ai.tool.${source.tool}`, { defaultValue: humanise(source.tool.split("_").slice(1).join("_")) })}</span>
        {period && <span className="text-muted"> · {period}</span>}
        <span className="text-muted"> · {t("ai.rows", { count: source.rows.length })}</span>
      </summary>
      <div className="space-y-2 px-3 pb-3">
        {source.rows.length === 0 ? <p className="text-sm text-muted">{t("ai.noRows")}</p> : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-line text-muted">{columns.map((c) => <th key={c} className={cx("py-1 pr-3 font-medium", right(c) && "text-right")}>{humanise(c)}</th>)}</tr>
              </thead>
              <tbody>
                {source.rows.map((row, i) => (
                  <tr key={i} className="border-b border-line/60 last:border-0">
                    {columns.map((c) => <td key={c} className={cx("tnum py-1 pr-3", right(c) && "text-right")}>{cellText(row[c])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {extras.length > 0 && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
            {extras.map(([k, v]) => <Fragment key={k}><dt className="text-muted">{humanise(k)}</dt><dd className="tnum">{cellText(v)}</dd></Fragment>)}
          </dl>
        )}
        {note && <p className="text-xs text-muted">{note}</p>}
      </div>
    </details>
  );
}
