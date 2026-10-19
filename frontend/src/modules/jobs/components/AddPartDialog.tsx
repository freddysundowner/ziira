import { useState } from "react";

import { api, Button, Checkbox, cx, Field, FormGrid, Input, Modal, NumberInput, Select, unwrap, useTranslation } from "@/sdk";

import { useJobAction, usePartCategories } from "../hooks";
import { ProductPicker } from "./pickers";

type Mode = "stock" | "hand" | "order" | "customer";
const MODES: Mode[] = ["stock", "hand", "order", "customer"];

/**
 * Use a part on the job: from stock (the store gives it up at once), bought in and priced by hand, ordered for this job
 * (it arrives later; stock is taken then) or brought by the customer (listed, never invoiced). A part can be genuine,
 * aftermarket or used, and a category prices it from its cost when no price is typed.
 */
export function AddPartDialog({ jobId, companyId, open, onClose, currency }: { jobId: string; companyId: string; open: boolean; onClose: () => void; currency: string | undefined }) {
  const { t } = useTranslation("jobs");
  const categories = usePartCategories(companyId, true);
  const [mode, setMode] = useState<Mode>("stock");
  const [productId, setProductId] = useState("");
  const [description, setDescription] = useState("");
  const [qty, setQty] = useState("1");
  const [price, setPrice] = useState("");
  const [cost, setCost] = useState("");
  const [partClass, setPartClass] = useState("");
  const [category, setCategory] = useState("");
  const [supplier, setSupplier] = useState("");
  const [order, setOrder] = useState("");
  const [expected, setExpected] = useState("");
  const [keepOld, setKeepOld] = useState(false);
  const reset = () => { setProductId(""); setDescription(""); setQty("1"); setPrice(""); setCost(""); setPartClass(""); setCategory(""); setSupplier(""); setOrder(""); setExpected(""); setKeepOld(false); };
  const usesProduct = mode === "stock" || (mode === "order" && !!productId);
  const add = useJobAction(jobId, () => unwrap(api.POST("/api/v1/jobs/jobs/{job_id}/parts", { params: { path: { job_id: jobId } }, body: {
    product_id: (mode === "stock" || mode === "order") && productId ? productId : null,
    description: description.trim() || null, quantity: qty, unit_price: price === "" ? null : price,
    part_class: (partClass || null) as "genuine" | "aftermarket" | "used" | null, category_code: category || null,
    customer_supplied: mode === "customer", order_for_job: mode === "order", cost_price: cost === "" ? null : cost,
    supplier_name: mode === "order" ? supplier.trim() || null : null, expected_on: mode === "order" ? expected || null : null,
    purchase_order_number: mode === "order" ? order.trim() || null : null, keep_old_part: keepOld } })),
  { done: t("parts.added"), onDone: () => { reset(); onClose(); } });
  const named = !!description.trim() || (usesProduct && !!productId);
  const priced = price !== "" || (usesProduct && mode === "stock") || mode === "customer" || (!!category && cost !== "") || (mode === "order" && !!productId);
  const ready = Number(qty) > 0 && named && priced;
  return (
    <Modal open={open} onClose={onClose} title={t("parts.addTitle")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={add.isPending} disabled={!ready} onClick={() => add.mutate()}>{t("parts.add")}</Button></>}>
      <div className="space-y-4">
        <div role="group" aria-label={t("parts.addTitle")} className="grid grid-cols-2 gap-1 rounded-xl bg-sunken p-1 sm:grid-cols-4">
          {MODES.map((m) => (
            <button key={m} type="button" aria-pressed={mode === m} onClick={() => setMode(m)} className={cx("h-11 rounded-lg px-1 text-sm font-medium", mode === m ? "bg-surface shadow-card" : "text-muted hover:text-ink")}>{t(`parts.mode.${m}`)}</button>
          ))}
        </div>
        <p className="text-sm text-muted">{t(`parts.modeHint.${mode}`)}</p>
        {(mode === "stock" || mode === "order") && <Field label={t("parts.product")} required={mode === "stock"}><ProductPicker value={productId} onChange={setProductId} /></Field>}
        {mode !== "stock" && <Field label={t("lines.description")} required={!productId}><Input maxLength={300} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>}
        <FormGrid>
          <Field label={t("lines.quantity")} required><NumberInput value={qty} onChange={setQty} /></Field>
          {mode !== "customer" && (
            <Field label={mode === "stock" ? t("parts.priceStock") : t("parts.priceHand")} required={mode === "hand"} hint={currency ? t("parts.priceHint", { currency }) : undefined}>
              <NumberInput value={price} onChange={setPrice} placeholder={mode === "stock" || productId ? t("parts.priceDefault") : category ? t("garage.parts.priceFromCost") : undefined} />
            </Field>
          )}
        </FormGrid>
        {mode !== "customer" && (
          <FormGrid>
            <Field label={t("garage.parts.category")} hint={t("garage.parts.categoryHint")}>
              <Select value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="">{t("garage.parts.noCategory")}</option>
                {(categories.data ?? []).map((c) => <option key={c.id} value={c.code}>{c.name} ({Number(c.markup_percent)}%)</option>)}
              </Select>
            </Field>
            {(mode === "hand" || mode === "order") && !usesProduct && (
              <Field label={t("garage.parts.cost")} hint={t("garage.parts.costHint")}><NumberInput value={cost} onChange={setCost} /></Field>
            )}
          </FormGrid>
        )}
        <Field label={t("garage.parts.class")}>
          <Select value={partClass} onChange={(e) => setPartClass(e.target.value)}>
            <option value="">{t("garage.parts.noClass")}</option>
            {(["genuine", "aftermarket", "used"] as const).map((c) => <option key={c} value={c}>{t(`garage.parts.classes.${c}`)}</option>)}
          </Select>
        </Field>
        {mode === "order" && (
          <FormGrid>
            <Field label={t("garage.parts.supplier")}><Input maxLength={160} value={supplier} onChange={(e) => setSupplier(e.target.value)} /></Field>
            <Field label={t("garage.parts.expected")}><Input type="date" value={expected} onChange={(e) => setExpected(e.target.value)} /></Field>
            <Field label={t("garage.parts.orderNumber")} hint={t("garage.parts.orderNumberHint")}><Input maxLength={40} value={order} onChange={(e) => setOrder(e.target.value)} /></Field>
          </FormGrid>
        )}
        <Checkbox label={t("garage.parts.keepOld")} checked={keepOld} onChange={(e) => setKeepOld(e.target.checked)} />
      </div>
    </Modal>
  );
}
