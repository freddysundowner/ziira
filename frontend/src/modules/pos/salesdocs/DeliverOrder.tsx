import { type FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  api, Alert, Button, Drawer, Field, FormGrid, Input, NumberInput, quantity, Schemas, Select, today, toast, unwrap, useMutation, useQueryClient, useTranslation,
} from "@/sdk";

import { useLocations } from "../hooks";
import { ProductName } from "./hooks";
import { deliveryLines, overDelivered, remainingToDeliver } from "./lib";

type Order = Schemas["DocOut"];

/** Deliver a confirmed order: all that is left by default, or the quantities typed. Delivering makes the invoice and takes the stock out. */
export function DeliverOrder({ order, open, onClose }: { order: Order; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("pos");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const locations = useLocations(order.branch_id, open);
  const left = Object.fromEntries(order.lines.map((l) => [l.id, remainingToDeliver(l)]));
  const [quantities, setQuantities] = useState<Record<string, string>>(left);
  const [locationId, setLocationId] = useState(order.location_id ?? "");
  const stores = locations.data?.filter((x) => x.is_active) ?? [];
  useEffect(() => { if (open && !locationId && stores.length === 1) setLocationId(stores[0].id); }, [open, locationId, stores.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const [issueDate, setIssueDate] = useState(today());
  // reopened after a partial delivery: start again from what is left now
  useEffect(() => { if (open) setQuantities(Object.fromEntries(order.lines.map((l) => [l.id, remainingToDeliver(l)]))); }, [open, order]);

  const chosen = deliveryLines(quantities);
  const tooMany = overDelivered(quantities, left);
  const blocked = chosen.length === 0 || tooMany.length > 0 || (stores.length > 0 && !locationId);

  const deliver = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/pos/orders/{document_id}/deliver", { params: { path: { document_id: order.id } }, body: {
      lines: chosen, location_id: locationId || null, issue_date: issueDate || null } })),
    onSuccess: (invoice) => {
      void qc.invalidateQueries({ queryKey: ["pos-docs"] });
      void qc.invalidateQueries({ queryKey: ["pos-doc"] });
      toast(t("docs.delivered_toast", { number: invoice.number }), "ok");
      onClose();
      navigate(`/pos/invoices/${invoice.id}`);
    },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (!blocked) deliver.mutate(); };

  return (
    <Drawer open={open} onClose={onClose} title={t("docs.deliverTitle", { number: order.number })}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="deliver-order" loading={deliver.isPending} disabled={blocked}>{t("docs.deliverAndInvoice")}</Button></>}>
      <form id="deliver-order" onSubmit={submit} className="space-y-4">
        <p className="text-sm text-muted">{t("docs.deliverHint")}</p>
        <div className="divide-y divide-line rounded-lg border border-line">
          {order.lines.map((l) => (
            <div key={l.id} className="flex items-center gap-3 p-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm"><ProductName id={l.product_id} /></p>
                <p className="text-xs text-muted">{t("docs.orderedDelivered", { ordered: quantity(l.quantity), delivered: quantity(l.qty_delivered) })}</p>
              </div>
              <Field label={t("docs.deliverNow")} error={tooMany.includes(l.id) ? t("docs.moreThanLeft", { left: quantity(left[l.id]) }) : null} className="w-32">
                <NumberInput value={quantities[l.id] ?? ""} invalid={tooMany.includes(l.id)} disabled={Number(left[l.id]) === 0}
                  onChange={(v) => setQuantities((q) => ({ ...q, [l.id]: v }))} />
              </Field>
            </div>
          ))}
        </div>
        <FormGrid>
          {stores.length > 0 && (
            <Field label={t("docs.deliverFrom")} hint={t("docs.deliverFromHint")} required>
              <Select value={locationId} onChange={(e) => setLocationId(e.target.value)}>
                <option value="">{t("docs.chooseStore")}</option>
                {stores.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
              </Select>
            </Field>
          )}
          <Field label={t("docs.issueDate")}><Input type="date" max={today()} value={issueDate} onChange={(e) => setIssueDate(e.target.value)} /></Field>
        </FormGrid>
        <Alert tone="info">{t("docs.deliverNote")}</Alert>
      </form>
    </Drawer>
  );
}
