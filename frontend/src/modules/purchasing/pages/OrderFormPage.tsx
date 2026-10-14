import { Plus, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  Alert, api, Button, Card, ErrorState, Field, FormGrid, IconButton, Input, money, NumberInput, PageHeader, Select, Skeleton, toast, today, unwrap,
  useCompany, useCurrency, useMutation, useQuery, useQueryClient, useTranslation, useUnsavedWarning,
} from "@/sdk";

import { CompanyBranch } from "../components/CompanyBranch";
import { LINE_ROW, useLines } from "../components/lines";
import { ProductPicker, SupplierPicker } from "../components/pickers";
import { useLocations } from "../hooks";
import { isPositive, previewSubtotal } from "../lib";

interface Line { key: string; product_id: string; quantity: string; unit_cost: string }
const blank = () => ({ product_id: "", quantity: "1", unit_cost: "" });

/** New purchase order, or edit a draft. Costs are before tax; the server adds tax and returns the totals. */
export default function OrderFormPage() {
  const { orderId } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const editing = !!orderId;
  const order = useQuery({ enabled: editing, queryKey: ["purchasing", "order", orderId], queryFn: () => unwrap(api.GET("/api/v1/purchasing/orders/{order_id}", { params: { path: { order_id: orderId ?? "" } } })) });
  const request = useQuery({ enabled: !!params.get("request"), queryKey: ["purchasing", "request", params.get("request")], queryFn: () => unwrap(api.GET("/api/v1/purchasing/requests/{request_id}", { params: { path: { request_id: params.get("request") ?? "" } } })) });

  if (editing && order.error) return <ErrorState message={order.error.message} onRetry={() => void order.refetch()} />;
  if (request.error) return <ErrorState message={request.error.message} onRetry={() => void request.refetch()} />;
  if ((editing && !order.data) || (params.get("request") && !request.data)) return <Skeleton className="h-60 w-full" />;
  const initial = order.data
    ? order.data.lines.map((l): Line => ({ key: l.id, product_id: l.product_id, quantity: l.quantity, unit_cost: l.unit_cost }))
    : request.data?.lines.map((l): Line => ({ key: l.id, product_id: l.product_id, quantity: l.quantity, unit_cost: "" })) ?? [];
  return <OrderForm key={order.data?.id ?? "new"} existing={order.data} initialLines={initial} requestId={request.data?.id}
    initialCompany={request.data?.company_id} initialBranch={request.data?.branch_id ?? ""} initialSupplier={params.get("supplier") ?? ""}
    onSaved={(id) => { void qc.invalidateQueries({ queryKey: ["purchasing"] }); navigate(`/orders/${id}`); }} />;
}

function OrderForm({ existing, initialLines, requestId, initialCompany, initialBranch, initialSupplier, onSaved }: {
  existing?: { id: string; company_id: string; supplier_id: string; branch_id: string | null; order_date: string; expected_date: string | null; deliver_to_location_id: string | null; status: string; number: string };
  initialLines: Line[]; requestId?: string; initialCompany?: string; initialBranch: string; initialSupplier: string; onSaved: (id: string) => void;
}) {
  const { t } = useTranslation("purchasing");
  const { company } = useCompany();
  const [companyId, setCompanyId] = useState(existing?.company_id ?? initialCompany ?? company?.id ?? "");
  const [branchId, setBranchId] = useState(existing?.branch_id ?? initialBranch);
  const [supplierId, setSupplierId] = useState(existing?.supplier_id ?? initialSupplier);
  const [orderDate, setOrderDate] = useState(existing?.order_date ?? today());
  const [expected, setExpected] = useState(existing?.expected_date ?? "");
  const [location, setLocation] = useState(existing?.deliver_to_location_id ?? "");
  const { lines, add, update, remove } = useLines<Line>(blank, initialLines.length ? initialLines : [{ ...blank(), key: crypto.randomUUID() }]);
  const currency = useCurrency(companyId);
  const locations = useLocations(companyId);
  const [touched, setTouched] = useState(false);
  useUnsavedWarning(touched);
  const touch = <A extends unknown[]>(fn: (...a: A) => void) => (...a: A) => { setTouched(true); fn(...a); };

  const filled = lines.filter((l) => l.product_id);
  const valid = !!supplierId && filled.length > 0 && filled.every((l) => isPositive(l.quantity) && l.unit_cost !== "");
  const body = filled.map((l) => ({ product_id: l.product_id, quantity: l.quantity, unit_cost: l.unit_cost }));

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => existing
      ? unwrap(api.PUT("/api/v1/purchasing/orders/{order_id}", { params: { path: { order_id: existing.id } }, body: { lines: body, expected_date: expected || null, deliver_to_location_id: location || null } }))
      : unwrap(api.POST("/api/v1/purchasing/orders", { body: { company_id: companyId, supplier_id: supplierId, lines: body, branch_id: branchId || null, deliver_to_location_id: location || null, order_date: orderDate, expected_date: expected || null, request_id: requestId ?? null } })),
    onSuccess: (o) => { setTouched(false); toast(t(existing ? "orderSaved" : "orderCreated", { number: o.number }), "ok"); onSaved(o.id); },
    onError: (e) => toast((e as Error).message, "bad"),
  });

  // When a product is chosen, offer the supplier's last price as the starting cost.
  async function chooseProduct(key: string, productId: string) {
    update(key, { product_id: productId });
    if (!productId || !supplierId) return;
    const prices = await unwrap(api.GET("/api/v1/purchasing/suppliers/{supplier_id}/prices", { params: { path: { supplier_id: supplierId }, query: { product_id: productId, limit: 10 } } })).catch(() => []);
    const last = [...prices].sort((a, b) => b.effective_date.localeCompare(a.effective_date))[0];
    if (last) update(key, { unit_cost: last.unit_cost });
  }
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <form onSubmit={submit}>
      <PageHeader back={{ to: existing ? `/orders/${existing.id}` : "/orders", label: existing ? existing.number : t("orders") }} title={existing ? t("editOrder", { number: existing.number }) : t("newOrder")} description={t("orderFormHint")}
        actions={<Button type="submit" loading={save.isPending} disabled={!valid}>{t("saveDraft")}</Button>} />
      <div className="space-y-4">
        <Card title={t("orderDetails")}>
          <FormGrid cols={3}>
            <CompanyBranch companyId={companyId} branchId={branchId} onCompany={touch(setCompanyId)} onBranch={touch(setBranchId)} lockCompany={!!existing} />
            <Field label={t("supplier")} required><SupplierPicker value={supplierId} onChange={touch(setSupplierId)} disabled={!!existing} /></Field>
            <Field label={t("orderDate")}><Input type="date" value={orderDate} disabled={!!existing} onChange={(e) => touch(setOrderDate)(e.target.value)} /></Field>
            <Field label={t("expectedDate")}><Input type="date" value={expected} min={orderDate} onChange={(e) => touch(setExpected)(e.target.value)} /></Field>
            {(locations.data?.length ?? 0) > 0 && (
              <Field label={t("deliverTo")}>
                <Select value={location} onChange={(e) => touch(setLocation)(e.target.value)}>
                  <option value="">{t("defaultLocation")}</option>
                  {locations.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                </Select>
              </Field>
            )}
          </FormGrid>
        </Card>
        <Card title={t("lines")} description={t("costsBeforeTax")}
          actions={<Button size="sm" variant="secondary" onClick={touch(() => add())}><Plus className="h-4 w-4" />{t("addLine")}</Button>}>
          {!supplierId && <Alert tone="info" className="mb-3">{t("pickSupplierFirst")}</Alert>}
          <div className="space-y-2">
            {lines.map((l, i) => (
              <div key={l.key} className={`${LINE_ROW} md:grid-cols-[minmax(0,1fr)_7rem_9rem_2.25rem]`}>
                <Field label={i === 0 ? t("product") : `${t("product")} ${i + 1}`}><ProductPicker value={l.product_id} onChange={(v) => { setTouched(true); void chooseProduct(l.key, v); }} /></Field>
                <Field label={t("quantity")}><NumberInput value={l.quantity} onChange={touch((v: string) => update(l.key, { quantity: v }))} /></Field>
                <Field label={t("unitCostBeforeTax")}><NumberInput value={l.unit_cost} onChange={touch((v: string) => update(l.key, { unit_cost: v }))} /></Field>
                <IconButton label={t("removeLine")} className="justify-self-end" disabled={lines.length === 1} onClick={touch(() => remove(l.key))}><Trash2 className="h-4 w-4" /></IconButton>
              </div>
            ))}
          </div>
          <p className="mt-4 text-right text-sm text-muted">{t("previewSubtotal")}: <span className="tnum font-medium text-ink">{money(previewSubtotal(filled), currency)}</span> <span className="text-xs">({t("previewNote")})</span></p>
        </Card>
      </div>
    </form>
  );
}
