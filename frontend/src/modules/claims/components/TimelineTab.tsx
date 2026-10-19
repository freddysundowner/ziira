import { Badge, Card, EmptyState, formatDate, useTranslation } from "@/sdk";

import type { Claim } from "../types";

/** Everything that happened on the claim, newest first: estimates sent, the payer's rounds, decisions, invoices, payments, notes. */
export function TimelineTab({ claim }: { claim: Claim }) {
  const { t } = useTranslation("claims");
  const events = [...claim.events].reverse();
  return (
    <Card title={t("timeline.title")} description={t("timeline.hint")}>
      {events.length === 0 ? <EmptyState title={t("timeline.empty")} /> : (
        <ol className="space-y-3">
          {events.map((e) => (
            <li key={e.id} className="flex gap-3 text-sm">
              <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand" aria-hidden />
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">{t(`timeline.kind.${e.kind}`, { defaultValue: e.kind })}</Badge>
                  <span className="text-xs text-muted">{formatDate(e.created_at, true)}{e.occurred_on ? ` · ${formatDate(e.occurred_on)}` : ""}{e.actor_name ? ` · ${e.actor_name}` : ""}</span>
                </p>
                {e.note && <p className="mt-0.5 whitespace-pre-line">{e.note}</p>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
