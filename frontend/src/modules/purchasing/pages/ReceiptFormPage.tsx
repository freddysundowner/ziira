import { Plus, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  Alert, api, Button, Card, ErrorState, Field, FormGrid, IconButton, Input, NumberInput, PageHeader, quantity, Select, Skeleton, toast, today, unwrap,
  useMutation, useQuery, useQueryClient, useTranslation, useUnsavedWarning,
} from "@/sdk";

import { BatchFields } from "../components/BatchFields";
import { LINE_ROW, useLines } from "../components/lines";
import { ProductName, SupplierName } from "../components/names";
import { ProductPicker, SupplierPicker } from "../components/pickers";
import { useLocations } from "../hooks";
import { dayToTimestamp, isPositive, stillToReceive } from "../lib";

interface Line { key: string; order_line_id: string; product_id: string; quantity: string; unit_cost: string; batch_no: string; expiry_date: string; expecting: string }

/** Receive goods against an order (?order=...) or on their own. The stock arrives in the same step, so the form sends once and then leaves. */
export default function ReceiptFormPage() {
  const { t } = useTranslation("purchasing");
  const [params] = useSearchParams();
  const orderId = params.get("order") ?? "";
  const order = useQuery({ enabled: !!orderId, queryKey: ["purchasing", "order", orderId], queryFn: () => unwrap(api.GET("/api/v1/purchasing/orders/{order_id}", { params: { path: { order_id: orderId } } })) });
  if (orderId && order.error) return <ErrorState title={t("orderNotFound")} message={order.error.message} onRetry={() => void order.refetch()} />;
  if (orderId && !order.data) return <Skeleton className="h-60 w-full" />;
  const lines = order.data?.lines.map((l): Line => ({
    key: l.id, order_line_id: l.id, product_id: l.product_id, quantity: stillToReceive(l), unit_cost: "", batch_no: "", expiry_date: "", expecting: stillToReceive(l),
  })) ?? [];
  return <ReceiptForm order={order.data} initialLines={lines} initialSupplier={params.get("supplier") ?? ""} />;
}

function ReceiptForm({ order, initialLines, initialSupplier }: {
  order?: { id: string; number: string; supplier_id: string; company_id: string; status: string }; initialLines: Line[]; initialSupplier: string;
}) {
  const { t } = useTranslation("purchasing");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [supplierId, setSupplierId] = useState(order?.supplier_id ?? initialSupplier);
  const [deliveryNote, setDeliveryNote] = useState("");
  const [day, setDay] = useState(today());
  const [location, setLocation] = useState("");
  const [landed, setLanded] = useState("");
  const [touched, setTouched] = useState(false);
  useUnsavedWarning(touched);
  const { lines, add, update, remove } = useLines<Line>(() => ({ order_line_id: "", product_id: "", quantity: "", unit_cost: "", batch_no: "", expiry_date: "", expecting: "" }), initialLines);
  const supplier = useQuery({ enabled: !!supplierId && !order, queryKey: ["purchasing", "supplier", supplierId], queryFn: () => unwrap(api.GET("/api/v1/purchasing/suppliers/{supplier_id}", { params: { path: { supplier_id: supplierId } } })) });
  const locations = useLocations(order?.company_id ?? supplier.data?.company_id);

  const receiving = lines.filter((l) => isPositive(l.quantity) && l.product_id);
  const valid = receiving.length > 0 && (!!order || (!!supplierId && receiving.every((l) => l.unit_cost !== "")));
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/purchasing/receipts", { body: {
      order_id: order?.id ?? null, supplier_id: order ? null : supplierId, location_id: location || null, delivery_note_no: deliveryNote.trim() || null,
      received_at: dayToTimestamp(day, today()) ?? null, landed_cost: landed || "0",
      lines: receiving.map((l) => ({ quantity: l.quantity, order_line_id: l.order_line_id || null, product_id: order ? null : l.product_id, unit_cost: order ? null : l.unit_cost,
        batch_no: l.batch_no.trim() || null, expiry_date: l.expiry_date || null })),
    } })),
    onSuccess: (r) => { setTouched(false); void qc.invalidateQueries({ queryKey: ["purchasing"] }); toast(t("receiptSaved", { number: r.number }), "ok"); navigate(`/receipts/${r.id}`); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const change = (fn: () => void) => { setTouched(true); fn(); };

  return (
    <form onSubmit={submit}>
      <PageHeader back={order ? { to: `/orders/${order.id}`, label: order.number } : { to: "/receipts", label: t("receipts") }} title={order ? t("receiveAgainst", { number: order.number }) : t("newReceipt")}
        description={order ? <SupplierName id={order.supplier_id} /> : t("receiptFormHint")}
        actions={<Button type="submit" loading={save.isPending} disabled={!valid}>{t("confirmReceipt")}</Button>} />
      <div className="space-y-4">
        <Card title={t("deliveryDetails")}>
          <FormGrid cols={3}>
            {!order && <Field label={t("supplier")} required><SupplierPicker value={supplierId} onChange={(v) => change(() => setSupplierId(v))} /></Field>}
            <Field label={t("deliveryNote")} hint={t("deliveryNoteHint")}><Input value={deliveryNote} maxLength={60} onChange={(e) => change(() => setDeliveryNote(e.target.value))} /></Field>
            <Field label={t("receivedOn")}><Input type="date" max={today()} value={day} onChange={(e) => change(() => setDay(e.target.value))} /></Field>
            {(locations.data?.length ?? 0) > 0 && (
              <Field label={t("receiveInto")}>
                <Select value={location} onChange={(e) => change(() => setLocation(e.target.value))}>
                  <option value="">{t("defaultLocation")}</option>
                  {locations.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                </Select>
              </Field>
            )}
            <Field label={t("landedCost")} hint={t("landedCostHint")}><NumberInput value={landed} onChange={(v) => change(() => setLanded(v))} /></Field>
          </FormGrid>
        </Card>
        <Card title={t("goodsReceived")} description={order ? t("partialOk") : undefined}
          actions={!order && <Button size="sm" variant="secondary" onClick={() => change(() => add())}><Plus className="h-4 w-4" />{t("addLine")}</Button>}>
          {lines.length === 0 && <Alert tone="info">{t("addLineToStart")}</Alert>}
          <div className="space-y-2">
            {lines.map((l) => (
              <div key={l.key} className={`${LINE_ROW} md:grid-cols-[minmax(0,1fr)_7rem] lg:grid-cols-[minmax(0,1fr)_7rem_9rem_9rem_9rem_2.25rem]`}>
                {order
                  ? <div><p className="text-xs font-medium uppercase tracking-wide text-muted">{t("product")}</p><p className="text-sm"><ProductName id={l.product_id} /></p>
                      <p className="text-xs text-muted">{t("stillExpected", { qty: quantity(l.expecting) })}</p></div>
                  : <Field label={t("product")}><ProductPicker value={l.product_id} onChange={(v) => change(() => update(l.key, { product_id: v }))} /></Field>}
                <Field label={t("quantityReceived")}><NumberInput value={l.quantity} onChange={(v) => change(() => update(l.key, { quantity: v }))} /></Field>
                {!order && <Field label={t("unitCostBeforeTax")}><NumberInput value={l.unit_cost} onChange={(v) => change(() => update(l.key, { unit_cost: v }))} /></Field>}
                <BatchFields productId={l.product_id} batchNo={l.batch_no} expiry={l.expiry_date} onBatch={(v) => change(() => update(l.key, { batch_no: v }))} onExpiry={(v) => change(() => update(l.key, { expiry_date: v }))} />
                {!order && <IconButton label={t("removeLine")} onClick={() => change(() => remove(l.key))}><Trash2 className="h-4 w-4" /></IconButton>}
              </div>
            ))}
          </div>
          {order && <p className="mt-3 text-xs text-muted">{t("zeroSkips")}</p>}
        </Card>
      </div>
    </form>
  );
}
