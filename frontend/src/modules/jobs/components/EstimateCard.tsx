import { Check, Pencil, Send, X } from "lucide-react";

import { Badge, Button, Card, formatDate, money, quantity, useTranslation } from "@/sdk";

import { estimateTone } from "../estimateForm";
import type { Estimate } from "../types";

/** One version of the estimate, its lines and what can be done with it. */
export function EstimateCard({ estimate, currency, canAct, onEdit, onSend, onDecide }: {
  estimate: Estimate; currency: string | undefined; canAct: boolean;
  onEdit: () => void; onSend: () => void; onDecide: (approve: boolean) => void;
}) {
  const { t } = useTranslation("jobs");
  const open = estimate.status === "draft" || estimate.status === "sent";
  return (
    <Card title={<span className="inline-flex items-center gap-2">{estimate.kind === "additional" ? t("garage.estimates.additionalVersion", { version: estimate.version }) : t("estimates.version", { version: estimate.version })}<Badge tone={estimateTone(estimate.status)}>{t(`estimates.status.${estimate.status}`, { defaultValue: estimate.status })}</Badge></span>}
      description={estimate.valid_until ? t("estimates.validUntilText", { date: formatDate(estimate.valid_until) }) : undefined}
      actions={canAct && open && (
        <>
          {estimate.status === "draft" && <Button size="sm" variant="secondary" onClick={onEdit}><Pencil className="h-4 w-4" />{t("estimates.edit")}</Button>}
          <Button size="sm" variant={estimate.status === "draft" ? "primary" : "secondary"} onClick={onSend}><Send className="h-4 w-4" />{estimate.status === "sent" ? t("estimates.sendAgain") : t("estimates.send")}</Button>
          {estimate.status === "sent" && <>
            <Button size="sm" variant="secondary" onClick={() => onDecide(true)}><Check className="h-4 w-4" />{t("estimates.saidYes")}</Button>
            <Button size="sm" variant="ghost" onClick={() => onDecide(false)}><X className="h-4 w-4" />{t("estimates.saidNo")}</Button>
          </>}
        </>
      )}>
      <ul className="divide-y divide-line text-sm">
        {estimate.lines.map((l) => (
          <li key={l.id} className="flex items-start justify-between gap-3 py-2">
            <span className="min-w-0"><span className="block">{l.description}{l.part_class && <Badge tone="neutral" className="ml-2">{t(`garage.parts.classes.${l.part_class}`)}</Badge>}</span><span className="tnum block text-xs text-muted">{quantity(l.quantity)} × {money(l.unit_price, currency)}</span></span>
            <span className="tnum shrink-0">{money(l.total, currency)}</span>
          </li>
        ))}
      </ul>
      <dl className="tnum mt-3 space-y-1 border-t border-line pt-3 text-sm">
        <div className="flex justify-between text-muted"><dt>{t("totals.tax")}</dt><dd>{money(estimate.tax, currency)}</dd></div>
        <div className="flex justify-between font-semibold"><dt>{t("totals.total")}</dt><dd>{money(estimate.total, currency)}</dd></div>
      </dl>
      {estimate.notes && <p className="mt-3 whitespace-pre-line text-sm text-muted">{estimate.notes}</p>}
      {estimate.decided_at && (
        <p className="mt-3 rounded-lg bg-sunken px-3 py-2 text-sm">
          {t("estimates.decidedBy", { name: estimate.decided_by_name ?? "—", date: formatDate(estimate.decided_at, true), via: t(`estimates.channel.${estimate.decision_channel ?? "staff"}`, { defaultValue: "" }) })}
          {estimate.decision_note && <span className="mt-1 block text-muted">{estimate.decision_note}</span>}
        </p>
      )}
    </Card>
  );
}
