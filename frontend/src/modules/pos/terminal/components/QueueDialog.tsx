import { Copy, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";

import { Alert, Badge, type BadgeTone, Button, ConfirmDialog, EmptyState, formatDate, Modal, money, toast, useTranslation } from "@/sdk";

import { dismissSale, retrySale, syncNow } from "../offline/controller";
import { useOutbox } from "../offline/hooks";
import { bySeq } from "../offline/outbox";
import { describeWarning } from "../offline/warnings";
import type { OutboxEntry } from "../offline/types";

const STATE_TONE: Record<OutboxEntry["state"], BadgeTone> = { pending: "warn", sending: "info", failed: "bad", done: "ok" };
const ORDER: Record<OutboxEntry["state"], number> = { failed: 0, pending: 1, sending: 1, done: 2 };

/** Sales made without a connection: waiting, refused (needs attention) and recently sent with a note. */
export function QueueDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation("pos");
  const { entries, counts, online, syncing, storageOk, warnings } = useOutbox();
  const [removing, setRemoving] = useState<OutboxEntry | null>(null);
  const shown = bySeq(entries).filter((e) => e.state !== "done" || e.warnings.length > 0).sort((a, b) => ORDER[a.state] - ORDER[b.state] || a.seq - b.seq);

  async function copy(e: OutboxEntry) {
    const details = JSON.stringify({ number: e.number, local_id: e.localId, made_at: new Date(e.madeAt).toISOString(), state: e.state, error: e.lastError, request: e.op }, null, 2);
    try {
      await navigator.clipboard.writeText(details);
      toast(t("terminal.sync.copied"), "ok");
    } catch {
      toast(t("terminal.sync.copyFailed"), "warn");
    }
  }

  return (
    <>
      <Modal open onClose={onClose} title={t("terminal.sync.title")} size="lg"
        footer={<>
          <Button variant="secondary" onClick={() => void syncNow(true)} disabled={syncing || counts.waiting === 0}><RefreshCw className="h-4 w-4" />{t("terminal.sync.sendNow")}</Button>
          <Button onClick={onClose}>{t("terminal.sync.close")}</Button>
        </>}>
        <div className="space-y-3">
          <p className="text-sm text-muted">{online ? t("terminal.sync.statusOnline", { count: counts.waiting }) : t("terminal.sync.statusOffline", { count: counts.waiting })}</p>
          {!storageOk && <Alert tone="bad">{t("terminal.sync.noStorage")}</Alert>}
          {warnings.includes("old") && <Alert tone="warn">{t("terminal.sync.oldWarning")}</Alert>}
          {warnings.includes("large") && <Alert tone="warn">{t("terminal.sync.largeWarning", { count: counts.waiting + counts.attention })}</Alert>}
          {shown.length === 0 ? (
            <EmptyState title={t("terminal.sync.empty")} hint={t("terminal.sync.emptyHint")} />
          ) : (
            <ul className="divide-y divide-line" data-testid="queue-list">
              {shown.map((e) => (
                <li key={e.localId} className="space-y-1.5 py-3" data-state={e.state}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-semibold">{e.serverNumber || e.number}</span>
                    <Badge tone={STATE_TONE[e.state]}>{t(`terminal.sync.state.${e.state}`)}</Badge>
                    {!e.serverNumber && <Badge tone="neutral">{t("terminal.sync.toConfirm")}</Badge>}
                    <span className="ml-auto tnum text-sm font-semibold">{money(e.total, e.currency)}</span>
                  </div>
                  <p className="text-xs text-muted">
                    {formatDate(new Date(e.madeAt), true)} · {t("terminal.sync.lines", { count: e.lines.length })}
                    {e.customerName && ` · ${e.customerName}`}
                  </p>
                  {e.state === "failed" && <Alert tone="bad">{t("terminal.sync.refused", { reason: e.lastError })}</Alert>}
                  {e.state === "pending" && e.lastError && <p className="text-xs text-warn">{t("terminal.sync.retrying", { reason: e.lastError, count: e.attempts })}</p>}
                  {e.state === "done" && e.warnings.length > 0 && (
                    <Alert tone="warn"><ul className="list-disc pl-4">{e.warnings.map((w) => <li key={w}>{describeWarning(w, t)}</li>)}</ul></Alert>
                  )}
                  <div className="flex flex-wrap gap-2">
                    {e.state === "failed" && <Button size="sm" onClick={() => void retrySale(e.localId)}><RefreshCw className="h-3.5 w-3.5" />{t("terminal.sync.retry")}</Button>}
                    {e.state !== "done" && <Button size="sm" variant="secondary" onClick={() => void copy(e)}><Copy className="h-3.5 w-3.5" />{t("terminal.sync.copy")}</Button>}
                    {e.state === "failed" && <Button size="sm" variant="ghost" onClick={() => setRemoving(e)}><Trash2 className="h-3.5 w-3.5" />{t("terminal.sync.remove")}</Button>}
                    {e.state === "done" && <Button size="sm" variant="secondary" onClick={() => void dismissSale(e.localId)}>{t("terminal.sync.dismiss")}</Button>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Modal>
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} danger title={t("terminal.sync.removeTitle")}
        message={t("terminal.sync.removeMessage", { number: removing?.number })} confirmLabel={t("terminal.sync.remove")}
        onConfirm={() => { if (removing) void dismissSale(removing.localId); setRemoving(null); }} />
    </>
  );
}
