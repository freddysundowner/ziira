import { EmptyState, formatDate, humanise, type Schemas, useTranslation } from "@/sdk";

type Event = Schemas["EventOut"];

/** The subscription's history, newest first as the server sends it: what happened, by whom, and the facts it carries. */
export function TimelineTab({ events }: { events: Event[] }) {
  const { t } = useTranslation("operator");
  const label = (kind: string) => kind.startsWith("status.")
    ? t("subscriber.timeline.statusChanged", { status: t(`status.${kind.slice(7)}`, humanise(kind.slice(7))) })
    : t(`subscriber.timeline.kinds.${kind.replace(/\./g, "_")}`, humanise(kind));
  if (events.length === 0) return <div className="rounded-xl border border-line bg-surface"><EmptyState title={t("subscriber.timeline.empty")} hint={t("subscriber.timeline.emptyHint")} /></div>;
  return (
    <ol className="space-y-3 rounded-xl border border-line bg-surface p-4 shadow-card">
      {events.map((e, i) => (
        <li key={`${e.occurred_at}-${i}`} className="border-l-2 border-line pl-3">
          <p className="text-sm font-medium">{label(e.kind)}</p>
          <p className="text-xs text-muted">{formatDate(e.occurred_at, true)}{e.by_name ? ` · ${e.by_name}` : ""}</p>
          {e.detail && Object.keys(e.detail).length > 0 && (
            <p className="mt-0.5 break-words font-mono text-xs text-muted">
              {Object.entries(e.detail).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join(" · ")}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
