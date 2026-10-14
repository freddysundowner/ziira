import { formatDate, humanise, useTranslation } from "@/sdk";
import type { Schemas } from "@/sdk";

type Event = Schemas["FindingEventOut"];

/** Who did what and when, oldest first. Events without a person were done by Intelligence itself. */
export default function Timeline({ events }: { events: readonly Event[] }) {
  const { t } = useTranslation("intel");
  if (events.length === 0) return <p className="text-sm text-muted">{t("noEvents")}</p>;
  const ordered = [...events].sort((a, b) => a.created_at.localeCompare(b.created_at));
  return (
    <ol className="relative space-y-4 border-l border-line pl-5">
      {ordered.map((e) => (
        <li key={e.id} className="relative">
          <span className="absolute -left-[25px] top-1.5 h-2 w-2 rounded-full bg-brand" aria-hidden />
          <p className="text-sm">
            <span className="font-medium">{t(`event.${e.event}`, humanise(e.event))}</span>
            <span className="text-muted"> · {e.user_name ?? t("bySystem")}{e.channel && e.channel !== "app" ? ` · ${t(`channel.${e.channel}`, humanise(e.channel))}` : ""}</span>
          </p>
          <p className="text-xs text-muted">{formatDate(e.created_at, true)}</p>
          {e.note && <p className="mt-1 whitespace-pre-wrap rounded-lg bg-sunken/60 px-3 py-2 text-sm">{e.note}</p>}
        </li>
      ))}
    </ol>
  );
}
