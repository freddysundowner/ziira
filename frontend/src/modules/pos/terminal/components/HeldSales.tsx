import { Trash2 } from "lucide-react";
import { useState } from "react";

import { Button, ConfirmDialog, EmptyState, formatDate, IconButton, Modal, money, useTranslation } from "@/sdk";

import { cartTotal, type HeldSale, text } from "../cart";

/** Sales parked while the customer fetches something. Resuming parks whatever is on the screen, so nothing is lost. */
export function HeldSales({ held, currency, onResume, onDelete, onClose }: {
  held: HeldSale[]; currency: string; onResume: (id: string) => void; onDelete: (id: string) => void; onClose: () => void;
}) {
  const { t } = useTranslation("pos");
  const [deleting, setDeleting] = useState<HeldSale | null>(null);
  return (
    <>
      <Modal open onClose={onClose} title={t("terminal.hold.title")} size="sm">
        {held.length === 0 ? <EmptyState title={t("terminal.hold.empty")} hint={t("terminal.hold.emptyHint")} /> : (
          <ul className="divide-y divide-line">
            {held.map((h) => (
              <li key={h.id} className="flex items-center gap-2 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{h.label}</p>
                  <p className="text-xs text-muted">{formatDate(h.savedAt, true)} · {t("terminal.hold.lines", { count: h.lines.length })}</p>
                </div>
                <span className="tnum text-sm font-semibold">{money(text(cartTotal(h.lines)), currency)}</span>
                <Button size="sm" onClick={() => onResume(h.id)}>{t("terminal.hold.resume")}</Button>
                <IconButton label={t("terminal.hold.delete")} onClick={() => setDeleting(h)}><Trash2 className="h-4 w-4" /></IconButton>
              </li>
            ))}
          </ul>
        )}
      </Modal>
      <ConfirmDialog open={!!deleting} onClose={() => setDeleting(null)} danger title={t("terminal.hold.deleteTitle")} message={t("terminal.hold.deleteMessage", { name: deleting?.label })}
        confirmLabel={t("terminal.hold.delete")} onConfirm={() => { if (deleting) onDelete(deleting.id); setDeleting(null); }} />
    </>
  );
}
