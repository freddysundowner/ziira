import { useState } from "react";

import { Alert, api, Button, Field, FormGrid, Modal, NumberInput, Select, unwrap, useQuery, useTranslation, money } from "@/sdk";

import { type CartLine, isPriceOverride, lineGross, lineProblem, num, needsReason, text } from "../cart";

/** Change a line: quantity, and (for people who may) the price and a discount, which then need a reason from the list. */
export function LineEditor({ line, currency, canOverride, online, savedReasons, onSave, onClose }: {
  line: CartLine; currency: string; canOverride: boolean; online: boolean; savedReasons: { id: string; label: string }[] | undefined;
  onSave: (patch: Partial<CartLine>) => void; onClose: () => void;
}) {
  const { t } = useTranslation("pos");
  const [quantity, setQuantity] = useState(line.quantity);
  const [price, setPrice] = useState(line.price);
  const [discountMode, setDiscountMode] = useState<"amount" | "percent">("amount");
  const [discount, setDiscount] = useState(line.discount === "0" ? "" : line.discount);
  const [reasonId, setReasonId] = useState(line.reasonId);

  const reasons = useQuery({
    enabled: canOverride && online,
    queryKey: ["pos-terminal", "reasons", "price_override"],
    queryFn: () => unwrap(api.GET("/api/v1/settings/reason-codes", { params: { query: { category: "price_override" } } })),
    staleTime: 5 * 60_000,
  });

  // Without a connection the list kept on this device is used.
  const reasonList = reasons.data?.filter((r) => r.is_active).map((r) => ({ id: r.id, label: r.label })) ?? savedReasons ?? [];
  const draft: CartLine = { ...line, quantity, price, reasonId };
  const gross = lineGross(draft);
  const discountAmount = discountMode === "percent" ? text((gross * num(discount)) / 100) : discount || "0";
  const candidate: CartLine = { ...draft, discount: discountAmount, reasonId: needsReason({ ...draft, discount: discountAmount }) ? reasonId : "" };
  const problem = lineProblem(candidate);
  const reasonNeeded = needsReason(candidate);

  const message = problem ? t(`terminal.line.problem.${problem}`) : null;
  return (
    <Modal open onClose={onClose} title={line.name} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("terminal.cancel")}</Button>
        <Button disabled={problem !== null} onClick={() => { onSave({ quantity, price, discount: discountAmount, reasonId: candidate.reasonId }); onClose(); }}>{t("terminal.line.save")}</Button></>}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (!problem) { onSave({ quantity, price, discount: discountAmount, reasonId: candidate.reasonId }); onClose(); } }}>
        <FormGrid cols={2}>
          <Field label={t("terminal.line.quantity")}><NumberInput value={quantity} onChange={setQuantity} autoFocus data-autofocus /></Field>
          <Field label={t("terminal.line.price")} hint={line.listPrice ? t("terminal.line.listPrice", { price: money(line.listPrice, currency) }) : t("terminal.line.noListPrice")}>
            <NumberInput value={price} onChange={setPrice} disabled={!canOverride} />
          </Field>
        </FormGrid>
        {canOverride && (
          <>
            <FormGrid cols={2}>
              <Field label={t("terminal.line.discount")}><NumberInput value={discount} onChange={setDiscount} /></Field>
              <Field label={t("terminal.line.discountIn")}>
                <Select value={discountMode} onChange={(e) => setDiscountMode(e.target.value as "amount" | "percent")}>
                  <option value="amount">{t("terminal.line.amount")}</option>
                  <option value="percent">{t("terminal.line.percent")}</option>
                </Select>
              </Field>
            </FormGrid>
            {reasonNeeded && (
              <Field label={t("terminal.line.reason")} required>
                <Select value={reasonId} onChange={(e) => setReasonId(e.target.value)} disabled={reasons.isLoading && reasonList.length === 0}>
                  <option value="">{t("terminal.line.chooseReason")}</option>
                  {reasonList.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
                </Select>
              </Field>
            )}
            {reasons.error && reasonList.length === 0 && <Alert tone="bad">{reasons.error.message}</Alert>}
          </>
        )}
        <div className="flex items-center justify-between rounded-lg bg-sunken px-3 py-2 text-sm">
          <span className="text-muted">{t("terminal.line.total")}</span>
          <span className="tnum font-semibold">{money(text(Math.max(0, gross - num(discountAmount))), currency)}</span>
        </div>
        {message && <p role="alert" className="text-xs text-bad">{message}</p>}
        {!canOverride && isPriceOverride(line) && <Alert tone="warn">{t("terminal.line.noPermission")}</Alert>}
        <button type="submit" className="hidden" />
      </form>
    </Modal>
  );
}
