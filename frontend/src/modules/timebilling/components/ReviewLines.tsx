import { Pencil, Trash2 } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import { api, Badge, Button, Field, IconButton, Input, Modal, money, NumberInput, toast, unwrap, useCan, useFormState, useMutation, useTranslation } from "@/sdk";

import { useRefresh } from "../hooks";
import { formatClock, formatDuration, LONG_MINUTES, linePreview, parseDuration } from "../lib";
import type { Review, ReviewLine } from "../types";
import { ServiceItemPicker } from "./ServiceItemPicker";

const TIME = "time";

const MONEY_KINDS = ["expense", "milestone"];

/** How far below what the work is worth a line is billed: "off" (nothing), "down" (less) or "full". */
function billing(line: ReviewLine): "full" | "down" | "off" {
  const worth = Number(line.list_amount ?? line.amount);
  const billed = Number(line.amount);
  return billed <= 0 && worth > 0 ? "off" : billed < worth - 0.004 ? "down" : "full";
}

/** The lines of a review. While it is a draft each line can be changed, written down or off (with a reason), or taken off. */
export function ReviewLines({ review, currency, editable, onRemove }: { review: Review; currency?: string; editable: boolean; onRemove: (line: ReviewLine) => void }) {
  const { t } = useTranslation("timebilling");
  const [editing, setEditing] = useState<string | null>(null);
  if (review.lines.length === 0) return <p className="px-4 py-8 text-center text-sm text-muted">{t("review.noLines")}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] text-sm">
        <thead>
          <tr className="border-b border-line bg-sunken text-left text-xs text-muted">
            <th scope="col" className="w-8 px-3 py-2 font-medium">#</th>
            <th scope="col" className="px-3 py-2 font-medium">{t("review.description")}</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">{t("review.hours")}</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">{t("review.rate")}</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">{t("review.amount")}</th>
            {editable && <th scope="col" className="w-20 px-3 py-2"><span className="sr-only">{t("review.actions")}</span></th>}
          </tr>
        </thead>
        <tbody>
          {review.lines.map((line) => {
            if (editing === line.id) return <EditRow key={line.id} review={review} line={line} currency={currency} onDone={() => setEditing(null)} />;
            const how = billing(line);
            return (
              <tr key={line.id} className="border-b border-line align-top last:border-0">
                <td className="tnum px-3 py-2 text-muted">{line.line_no}</td>
                <td className="px-3 py-2">
                  <p className="font-medium">{line.description}</p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                    <Badge>{t(`review.kind.${line.kind}`, line.kind)}</Badge>
                    {line.kind === TIME && line.entry_count > 0 && t("review.fromEntries", { count: line.entry_count })}
                    {line.kind === "expense" && line.expense_count > 0 && t("review.fromExpenses", { count: line.expense_count })}
                    {how === "down" && <Badge tone="warn">{t("review.writtenDown")}</Badge>}
                    {how === "off" && <Badge tone="bad">{t("review.writtenOff")}</Badge>}
                    {line.automatic && <Badge tone="info">{t("review.feeCap")}</Badge>}
                  </p>
                  {how !== "full" && line.write_down_reason && <p className="mt-1 text-xs text-muted">{t("review.reasonIs", { reason: line.write_down_reason })}</p>}
                </td>
                <td className="tnum px-3 py-2 text-right">
                  {line.minutes === null ? "—" : formatDuration(line.minutes)}
                  {how !== "full" && line.list_minutes !== null && line.list_minutes !== line.minutes && <span className="block text-xs text-muted line-through">{formatDuration(line.list_minutes)}</span>}
                </td>
                <td className="tnum px-3 py-2 text-right">{line.kind === TIME ? (line.rate === null ? <Badge tone="bad">{t("review.noRate")}</Badge> : money(line.rate, currency)) : "—"}</td>
                <td className="tnum px-3 py-2 text-right font-medium">
                  {money(line.amount, currency)}
                  {how !== "full" && <span className="block text-xs font-normal text-muted line-through">{money(line.list_amount ?? line.amount, currency)}</span>}
                </td>
                {editable && (
                  <td className="px-2 py-1.5 text-right">
                    <IconButton label={t("edit")} onClick={() => setEditing(line.id)}><Pencil className="h-4 w-4" /></IconButton>
                    <IconButton label={t("review.removeLine")} onClick={() => onRemove(line)}><Trash2 className="h-4 w-4" /></IconButton>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function EditRow({ review, line, currency, onDone }: { review: Review; line: ReviewLine; currency?: string; onDone: () => void }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const partner = useCan("time.partner");
  const isTime = line.kind === TIME;
  const money_ = MONEY_KINDS.includes(line.kind);
  const f = useFormState({ description: line.description, hours: line.minutes ? formatClock(line.minutes) : "", rate: line.rate ?? "", amount: line.amount, reason: line.write_down_reason ?? "" });
  const minutes = parseDuration(f.values.hours, LONG_MINUTES);          // a grouped line can run past a day
  const worth = Number(line.list_amount ?? line.amount);
  const billed = isTime ? Number(linePreview(minutes, f.values.rate) ?? line.amount) : money_ ? Number(f.values.amount) : null;
  const below = billed !== null && billed < worth - 0.004;
  const off = billed !== null && billed <= 0 && worth > 0;
  const above = billed !== null && billed > worth + 0.004;
  const needsReason = below && !f.values.reason.trim();
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.PATCH("/api/v1/timebilling/invoice-reviews/{batch_id}/lines/{line_id}", { params: { path: { batch_id: review.id, line_id: line.id } }, body: {
      description: f.values.description.trim(),
      ...(isTime ? { minutes: minutes ?? undefined, rate: f.values.rate === "" ? undefined : f.values.rate } : money_ ? { amount: f.values.amount } : { amount: f.values.amount }),
      ...(below ? { write_down_reason: f.values.reason.trim() } : {}) } })),
    onSuccess: () => { void refresh(); onDone(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const preview = isTime ? linePreview(minutes, f.values.rate) : null;
  const bad = (isTime && (minutes === null || (minutes === 0 && !partner))) || above || needsReason || (off && !partner) || (!isTime && !f.values.amount);
  const writeOff = () => { if (isTime) f.set("hours", "0"); else f.set("amount", "0"); };
  return (
    <tr className="border-b border-line bg-sunken/60 align-top">
      <td className="tnum px-3 py-2 text-muted">{line.line_no}</td>
      <td colSpan={isTime ? 1 : 3} className="px-3 py-2">
        <form id={`line-${line.id}`} onSubmit={submit} className="space-y-2">
          <Field label={t("review.description")} error={f.error("description")}><Input {...f.bind("description")} maxLength={300} required data-autofocus /></Field>
          {isTime && <p className="text-xs text-muted">{t("review.timeLineHint", { max: formatDuration(line.list_minutes ?? line.minutes) })}</p>}
          {below && (
            <Field label={t("review.reason")} required hint={off ? t("review.writeOffHint") : t("review.writeDownHint", { amount: money(String(worth - (billed ?? 0)), currency) })} error={f.error("write_down_reason")}>
              <Input {...f.bind("reason")} maxLength={300} placeholder={t("review.reasonHint")} />
            </Field>
          )}
          {above && <p className="text-xs text-bad">{t("review.cannotExceed", { amount: money(String(worth), currency) })}</p>}
          {off && !partner && <p className="text-xs text-bad">{t("review.partnerOnly")}</p>}
          {partner && (isTime || money_) && !off && line.kind !== "milestone" && <button type="button" className="text-xs font-medium text-brand-strong hover:underline" onClick={writeOff}>{t("review.writeOff")}</button>}
        </form>
      </td>
      {isTime && (
        <>
          <td className="px-3 py-2"><Field label={t("review.hours")} error={f.error("minutes") ?? (f.values.hours !== "" && minutes === null ? t("timeInvalid") : null)}><Input form={`line-${line.id}`} className="tnum text-right" {...f.bind("hours")} /></Field></td>
          <td className="px-3 py-2"><Field label={t("review.rate")} error={f.error("rate")}><NumberInput value={f.values.rate} onChange={(v) => f.set("rate", v)} /></Field></td>
          <td className="tnum px-3 py-2 pt-9 text-right text-muted">{preview ? t("review.estimate", { amount: money(preview, currency) }) : "—"}</td>
        </>
      )}
      {!isTime && <td className="px-3 py-2"><Field label={t("review.amount")} error={f.error("amount")}><NumberInput value={f.values.amount} onChange={(v) => f.set("amount", v)} /></Field></td>}
      <td className="px-2 py-2 pt-8 text-right">
        <div className="flex justify-end gap-1">
          <Button size="sm" type="submit" form={`line-${line.id}`} loading={save.isPending} disabled={bad}>{t("save")}</Button>
          <Button size="sm" variant="ghost" onClick={onDone}>{t("cancel")}</Button>
        </div>
      </td>
    </tr>
  );
}

/** A line of your own: a fee or an adjustment. */
export function ManualLineDialog({ review, open, onClose }: { review: Review; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const f = useFormState({ description: "", amount: "" });
  const [service, setService] = useState("");
  const { reset } = f;
  useEffect(() => { if (open) { reset(); setService(""); }   }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/timebilling/invoice-reviews/{batch_id}/lines", { params: { path: { batch_id: review.id } }, body: { description: f.values.description.trim(), amount: f.values.amount, service_product_id: service || null } })),
    onSuccess: () => { void refresh(); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Modal open={open} onClose={onClose} title={t("review.addLine")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="manual-line" loading={save.isPending} disabled={!f.values.description.trim() || !(Number(f.values.amount) > 0)}>{t("review.addLine")}</Button></>}>
      <form id="manual-line" onSubmit={submit} className="space-y-4">
        <Field label={t("review.description")} required error={f.error("description")}><Input {...f.bind("description")} maxLength={300} required placeholder={t("review.descriptionHint")} /></Field>
        <Field label={t("review.amount")} required error={f.error("amount")}><NumberInput value={f.values.amount} onChange={(v) => f.set("amount", v)} required /></Field>
        <Field label={t("projects.serviceItem")} hint={t("review.serviceItemHint")} error={f.error("service_product_id")}><ServiceItemPicker value={service} onChange={setService} /></Field>
      </form>
    </Modal>
  );
}
