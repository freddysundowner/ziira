import { AlertTriangle, ChevronDown, ChevronRight, Link2, MessageSquareReply, Pencil, Printer, Send, Undo2, X } from "lucide-react";
import { useState } from "react";

import { Alert, Badge, Button, Card, cx, formatDate, Menu, money, quantity, useTranslation } from "@/sdk";

import { canAnswer } from "../lib";
import type { Estimate, EstimateLine } from "../types";
import { AnswerBadge, WaitingBadge } from "./StatusBits";

export interface EstimateHandlers {
  onEdit: (e: Estimate) => void;
  onSend: (e: Estimate) => void;
  onAnswer: (e: Estimate) => void;
  onRevise: (e: Estimate) => void;
  onLinks: (e: Estimate) => void;
  onPrint: (e: Estimate) => void;
  onWithdraw: (e: Estimate) => void;
  onCounter: (l: EstimateLine) => void;
  onCustomer: (l: EstimateLine) => void;
  onReduce: (l: EstimateLine) => void;
}

const statusTone = (s: string) => (s === "answered" ? "ok" : s === "submitted" ? "warn" : s === "draft" ? "neutral" : "neutral");

/** One version of the estimate with the payer's answer beside each line: what we asked, what they said, who pays what. */
export function EstimateCard({ estimate, currency, canEstimate, canInvoice, closed, handlers, latest }: {
  estimate: Estimate; currency: string | undefined; canEstimate: boolean; canInvoice: boolean; closed: boolean; handlers: EstimateHandlers; latest: boolean;
}) {
  const { t } = useTranslation("claims");
  const live = estimate.status === "submitted" || estimate.status === "answered";
  const act = canEstimate && !closed;
  const waiting = estimate.lines.some(canAnswer);
  const payerPays = estimate.lines.reduce((n, l) => n + Number(l.payer_pays), 0);
  const customerPays = estimate.lines.reduce((n, l) => n + Number(l.customer_pays), 0);
  return (
    <Card
      title={<span className="inline-flex flex-wrap items-center gap-2">{estimate.label}{estimate.title ? ` · ${estimate.title}` : ""}<Badge tone={statusTone(estimate.status)}>{t(`estimate.status.${estimate.status}`, { defaultValue: estimate.status })}</Badge>{estimate.in_play && <Badge tone="brand">{t("estimate.inPlay")}</Badge>}</span>}
      description={[
        estimate.submitted_at ? t("estimate.sentOn", { date: formatDate(estimate.submitted_at, true), via: t(`estimate.via.${estimate.submitted_via ?? "hand"}`, { defaultValue: estimate.submitted_via ?? "" }) }) : t("estimate.notSent"),
        estimate.valid_until ? t("estimate.validUntil", { date: formatDate(estimate.valid_until) }) : null,
      ].filter(Boolean).join(" · ")}
      actions={(
        <>
          <Button size="sm" variant="ghost" onClick={() => handlers.onPrint(estimate)}><Printer className="h-4 w-4" /><span className="hidden sm:inline">{t("estimate.print")}</span></Button>
          {act && estimate.status === "draft" && (
            <>
              <Button size="sm" variant="secondary" onClick={() => handlers.onEdit(estimate)}><Pencil className="h-4 w-4" />{t("estimate.edit")}</Button>
              <Button size="sm" onClick={() => handlers.onSend(estimate)}><Send className="h-4 w-4" />{t("estimate.send")}</Button>
            </>
          )}
          {act && estimate.status === "submitted" && waiting && <Button size="sm" onClick={() => handlers.onAnswer(estimate)}><MessageSquareReply className="h-4 w-4" />{t("estimate.recordAnswer")}</Button>}
          {act && live && latest && estimate.in_play && <Button size="sm" variant="secondary" onClick={() => handlers.onRevise(estimate)}>{t("estimate.newVersion")}</Button>}
          {act && (estimate.status === "draft" || estimate.status === "submitted") && (
            <Menu label={t("estimate.more")} trigger={<span className="inline-flex h-8 items-center rounded-md px-2 text-sm text-muted hover:bg-sunken">{t("estimate.more")}</span>}
              items={[
                ...(estimate.status === "submitted" ? [{ label: t("estimate.links"), icon: <Link2 className="h-4 w-4" />, onSelect: () => handlers.onLinks(estimate) }] : []),
                { label: estimate.status === "draft" ? t("estimate.discard") : t("estimate.withdraw"), icon: <X className="h-4 w-4" />, danger: true, onSelect: () => handlers.onWithdraw(estimate) },
              ]} />
          )}
        </>
      )}>
      {estimate.over_approval_limit && <Alert tone="warn" className="mb-3"><AlertTriangle className="mr-1 inline h-4 w-4" />{t("estimate.overLimit")}</Alert>}
      {estimate.revision_note && <p className="mb-3 rounded-lg bg-sunken px-3 py-2 text-sm"><span className="font-medium">{t("estimate.revisionNote")}: </span>{estimate.revision_note}</p>}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-xs uppercase tracking-wide text-muted">
            <tr>
              <th scope="col" className="py-2 pr-2 font-medium">{t("lines.item")}</th>
              <th scope="col" className="px-2 py-2 text-right font-medium">{t("lines.asked")}</th>
              <th scope="col" className="px-2 py-2 font-medium">{t("lines.answer")}</th>
              <th scope="col" className="hidden px-2 py-2 text-right font-medium md:table-cell">{t("lines.payerPays")}</th>
              <th scope="col" className="hidden px-2 py-2 text-right font-medium md:table-cell">{t("lines.customerPays")}</th>
              <th scope="col" className="w-px py-2 pl-2"><span className="sr-only">{t("lines.next")}</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {estimate.lines.map((l) => <LineRows key={l.id} line={l} currency={currency} handlers={handlers} act={act && estimate.in_play} canInvoice={canInvoice && !closed} />)}
          </tbody>
          <tfoot className="border-t border-line font-semibold">
            <tr>
              <td className="py-2 pr-2">{t("lines.total")}</td>
              <td className="tnum px-2 py-2 text-right">{money(estimate.total, currency)}</td>
              <td className="px-2 py-2" />
              <td className="tnum hidden px-2 py-2 text-right md:table-cell">{estimate.in_play ? money(payerPays, currency) : ""}</td>
              <td className="tnum hidden px-2 py-2 text-right md:table-cell">{estimate.in_play ? money(customerPays, currency) : ""}</td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
      {estimate.notes && <p className="mt-3 whitespace-pre-line text-sm text-muted">{estimate.notes}</p>}
      {estimate.responses.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-muted">
          {estimate.responses.map((r) => (
            <li key={r.round}>
              {t("estimate.round", { n: r.round })}: {t(`response.${r.response}`, { defaultValue: r.response })} · {r.by_name} · {r.channel === "link" ? t("estimate.onLink") : t(`via.${r.via ?? "other"}`, { defaultValue: r.via ?? "" })} · {formatDate(r.occurred_at, true)}
              {r.authority_ref ? ` · ${t("estimate.authority", { ref: r.authority_ref })}` : ""}{r.note ? ` · ${r.note}` : ""}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function LineRows({ line: l, currency, handlers, act, canInvoice }: { line: EstimateLine; currency: string | undefined; handlers: EstimateHandlers; act: boolean; canInvoice: boolean }) {
  const { t } = useTranslation("claims");
  const [open, setOpen] = useState(false);
  const rounds = l.history.length;
  return (
    <>
      <tr className={cx(l.locked && "bg-sunken/40")}>
        <td className="max-w-[16rem] py-2.5 pr-2 align-top">
          <span className="block font-medium">{l.description}</span>
          <span className="tnum block text-xs text-muted">
            {t(`kind.${l.kind}`, { defaultValue: l.kind })}{l.part_class ? ` · ${t(`partClass.${l.part_class}`)}` : ""} · {quantity(l.quantity)} × {money(l.unit_price, currency)}
            {l.locked ? ` · ${t("lines.settled")}` : ""}
          </span>
          <span className="mt-1 flex flex-wrap gap-1 md:hidden">
            <span className="tnum text-xs text-muted">{t("lines.payerPays")}: {money(l.payer_pays, currency)}</span>
            {Number(l.customer_pays) > 0 && <span className="tnum text-xs text-muted">· {t("lines.customerPays")}: {money(l.customer_pays, currency)}</span>}
          </span>
        </td>
        <td className="tnum px-2 py-2.5 text-right align-top">{money(l.asked_total, currency)}</td>
        <td className="px-2 py-2.5 align-top">
          <span className="flex flex-wrap items-center gap-1.5">
            <AnswerBadge state={l.payer_state} />
            {l.payer_state === "countered" && <span className="tnum text-sm font-medium">{money(l.payer_amount, currency)}</span>}
            <WaitingBadge waiting={l.waiting_on} />
          </span>
          {l.payer_reason && <span className="mt-0.5 block text-xs text-muted">{l.payer_reason}</span>}
          {l.our_decision && <span className="block text-xs text-muted">{t(`decision.our.${l.our_decision}`)}{l.shortfall_to && l.our_decision === "accepted" ? ` · ${t(`decision.carried.${l.shortfall_to}`)}` : ""}</span>}
          {l.customer_decision && l.payer_state === "rejected" && <span className="block text-xs text-muted">{t(`decision.customer.${l.customer_decision}`, { name: l.customer_decision_by ?? "" })}</span>}
          {rounds > 0 && (
            <button type="button" className="mt-0.5 inline-flex items-center gap-0.5 text-xs text-muted hover:text-ink" aria-expanded={open} onClick={() => setOpen(!open)}>
              {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}{t("lines.history", { n: rounds })}
            </button>
          )}
        </td>
        <td className="tnum hidden px-2 py-2.5 text-right align-top md:table-cell">{money(l.payer_pays, currency)}</td>
        <td className="tnum hidden px-2 py-2.5 text-right align-top md:table-cell">{money(l.customer_pays, currency)}</td>
        <td className="whitespace-nowrap py-2.5 pl-2 text-right align-top">
          {act && l.waiting_on === "us" && l.payer_state === "countered" && (
            <Button size="sm" variant="secondary" onClick={() => handlers.onCounter(l)}>{t("lines.decideOffer")}</Button>
          )}
          {act && l.waiting_on === "customer" && <Button size="sm" variant="secondary" onClick={() => handlers.onCustomer(l)}>{t("lines.customerDecides")}</Button>}
          {canInvoice && l.invoiced && Number(l.payer_pays) > 0 && (
            <Button size="sm" variant="ghost" onClick={() => handlers.onReduce(l)}><Undo2 className="h-4 w-4" />{t("lines.reduced")}</Button>
          )}
        </td>
      </tr>
      {open && (
        <tr className="bg-sunken/40">
          <td colSpan={6} className="px-3 py-2">
            <ol className="space-y-1 text-xs text-muted">
              {l.history.map((h, i) => (
                <li key={i}>
                  {t("estimate.round", { n: h.round })}: <span className="font-medium text-ink">{t(`answer.${h.state}`, { defaultValue: h.state })}</span>
                  {h.amount ? ` ${money(h.amount, currency)}` : ""} · {h.by_name ?? "—"} · {h.channel === "link" ? t("estimate.onLink") : t(`via.${h.via ?? "other"}`, { defaultValue: h.via ?? "" })} · {formatDate(h.answered_at, true)}{h.reason ? ` · ${h.reason}` : ""}
                </li>
              ))}
            </ol>
          </td>
        </tr>
      )}
    </>
  );
}
