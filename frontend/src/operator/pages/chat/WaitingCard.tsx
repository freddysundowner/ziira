import { useQuery } from "@tanstack/react-query";

import { Badge, Button, Card, EmptyState, formatDate, Skeleton, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { useChange } from "../../stepUp";
import { type ChatOverview, outcomeKeys } from "./logic";

/** People who asked for a person (masked numbers) and what the last conversations came to (counts only). */
export function WaitingCard({ overview: o, editable, onChanged }: { overview: ChatOverview; editable: boolean; onChanged: () => void }) {
  const { t } = useTranslation("operator");
  const list = useQuery({ queryKey: ["operator", "chat", "handoffs", o.stats.open_handoffs], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/chat/handoffs", { params: { query: { status: "open" } } })) });
  const done = useChange((id: string) => opUnwrap(opApi.POST("/api/v1/operator/chat/handoffs/{handoff_id}/done", { params: { path: { handoff_id: id } } })), {
    onSuccess: () => { toast(t("chat.waiting.doneToast"), "ok"); void list.refetch(); onChanged(); },
  });
  const s = o.stats;
  return (
    <Card title={t("chat.waiting.title")} description={t("chat.waiting.intro")}
      actions={<Badge tone={s.open_handoffs > 0 ? "warn" : "neutral"}>{t("chat.waiting.count", { count: s.open_handoffs })}</Badge>}>
      <div className="space-y-4">
        {list.isPending ? <Skeleton className="h-16 w-full" /> : list.isError ? <p className="text-sm text-bad">{list.error.message}</p> : list.data.length === 0 ? (
          <EmptyState title={t("chat.waiting.empty")} hint={t("chat.waiting.emptyHint")} />
        ) : (
          <ul className="divide-y divide-line" aria-label={t("chat.waiting.title")}>
            {list.data.map((h) => (
              <li key={h.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <div className="min-w-0">
                  <p className="font-medium tnum">{h.sender_masked} <span className="font-normal text-muted">{formatDate(h.created_at, true)}</span></p>
                  <p className="break-words text-muted">{h.snippet ?? t("chat.waiting.noSnippet")}</p>
                </div>
                {editable && <Button size="sm" variant="secondary" loading={done.isPending && done.variables === h.id} onClick={() => done.mutate(h.id)}>{t("chat.waiting.markDone")}</Button>}
              </li>
            ))}
          </ul>
        )}
        <div>
          <p className="mb-1 text-xs text-muted">{t("chat.waiting.lastConversations", { count: s.last })}</p>
          <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4" data-testid="counters">
            {outcomeKeys.map((k) => (
              <div key={k} className="rounded-lg bg-sunken px-3 py-2"><dt className="text-muted">{t(`chat.waiting.outcomes.${k}`)}</dt><dd className="tnum text-lg font-semibold">{s[k]}</dd></div>
            ))}
          </dl>
        </div>
      </div>
    </Card>
  );
}
