import { Badge, type BadgeTone, humanise, formatDate, useTranslation } from "@/sdk";

import type { ErasureOutcome } from "./model";

const TONE: Record<string, BadgeTone> = { anonymised: "ok", partial: "warn", refused: "bad" };

/** What an erasure did, record by record: what changed, what was kept and why. */
export default function ErasureResults({ erasure, userName }: { erasure: ErasureOutcome; userName: (id: string | null) => string }) {
  const { t } = useTranslation("kernel");
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">
        {t("dsr.erase.ranOn", { date: formatDate(erasure.at, true) })} {t("dsr.erase.reasonWas", { reason: erasure.reason })}{" "}
        {erasure.requestedBy && t("dsr.erase.requestedBy", { name: userName(erasure.requestedBy) })}{" "}
        {erasure.approvedBy ? t("dsr.erase.approvedBy", { name: userName(erasure.approvedBy) }) : t("dsr.erase.noApproval")}
      </p>
      <ul className="space-y-2">
        {erasure.results.map((r, i) => (
          <li key={i} className="rounded-lg border border-line p-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">{t(`dsr.source.${r.source}`, { defaultValue: humanise(r.source) })} · {humanise(r.kind)}</span>
              <Badge tone={TONE[r.status] ?? "neutral"}>{t(`dsr.erase.result.${r.status}`, { defaultValue: humanise(r.status) })}</Badge>
            </div>
            {r.changed.length > 0 && <p className="mt-1 text-muted"><span className="font-medium text-ink">{t("dsr.erase.changed")}:</span> {r.changed.map(humanise).join(", ")}</p>}
            {r.kept.length > 0 && (
              <div className="mt-1">
                <p className="font-medium">{t("dsr.erase.kept")}:</p>
                <ul className="list-inside list-disc text-muted">{r.kept.map((k, j) => <li key={j}><span className="text-ink">{k.what}</span>: {k.why}</li>)}</ul>
              </div>
            )}
            {r.message && <p className="mt-1 text-muted">{r.message}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}
