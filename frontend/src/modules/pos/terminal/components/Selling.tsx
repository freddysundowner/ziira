import { Lock } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  api, Button, ConfirmDialog, cx, toast, unwrap, useCan, useMutation, useQueryClient, useSession, useTranslation, type Schemas,
} from "@/sdk";

import type { BranchInfo } from "../branches";
import {
  addItem, type CartLine, cartProblem, cartTotal, EMPTY_CART, fingerprint, itemCount, newLeg, patchLine, removeLine, stepQuantity, text, toSaleLines, toSalePayments,
  type CatalogItem,
} from "../cart";
import { forgetTill, useCart, useHeld } from "../hooks";
import { CartPanel } from "./CartPanel";
import { CloseTill } from "./CloseTill";
import { CustomerPicker } from "./CustomerPicker";
import { Frame } from "./Frame";
import { HeldSales } from "./HeldSales";
import { LineEditor } from "./LineEditor";
import { PaymentDialog } from "./PaymentDialog";
import { ProductPanel } from "./ProductPanel";
import { SaleDone } from "./SaleDone";

type Dialog = "pay" | "held" | "close" | null;

/** The terminal proper: products on the left, the cart on the right, payment and closing in dialogs. */
export function Selling({ till, device, branch }: { till: Schemas["TillOut"]; device: Schemas["DeviceOut"] | undefined; branch: BranchInfo }) {
  const { t } = useTranslation("pos");
  const qc = useQueryClient();
  const { me, enabledUnits } = useSession();
  const canOverride = useCan("price.override");
  const canPickCustomer = useCan("customers.view") && enabledUnits.has("crm");
  const currency = branch.currency;

  const { state, edit, setLegs, setAttempt, clear, replace } = useCart(till.id);
  const { held, update } = useHeld(till.id);
  const [view, setView] = useState<"products" | "cart">("products");
  const [dialog, setDialog] = useState<Dialog>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);
  const [done, setDone] = useState<Schemas["SaleOut"] | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const lines = state.lines;
  const total = cartTotal(lines);
  const canPay = lines.length > 0 && cartProblem(lines) === null;
  const editingLine = lines.find((l) => l.key === editing);

  const setLines = useCallback((change: (lines: CartLine[]) => CartLine[]) => edit((s) => ({ ...s, lines: change(s.lines) })), [edit]);
  const add = (item: CatalogItem) => setLines((l) => addItem(l, item));

  // One id per distinct sale: a retry of the same content (after a dropped connection) is recorded once; a changed cart gets a new id.
  const sell = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const print = fingerprint(state);
      const attempt = state.attempt?.fingerprint === print ? state.attempt : { id: crypto.randomUUID(), fingerprint: print };
      setAttempt(attempt);
      return unwrap(api.POST("/api/v1/pos/sales", {
        body: { till_session_id: till.id, lines: toSaleLines(lines), payments: toSalePayments(state.legs), customer_id: state.customerId || null, local_id: attempt.id },
      }));
    },
    onSuccess: (sale) => {
      clear();
      setDialog(null);
      setView("products");
      setDone(sale);
      void qc.invalidateQueries({ queryKey: ["pos-terminal", "catalog"] });
    },
  });

  const openPay = useCallback(() => {
    if (!canPay) return;
    if (state.legs.length === 0) setLegs(() => [newLeg("cash", total)]);
    sell.reset();
    setDialog("pay");
  }, [canPay, state.legs.length, total, setLegs, sell]);

  const hold = useCallback(() => {
    if (lines.length === 0) return;
    const time = new Intl.DateTimeFormat(undefined, { timeStyle: "short" }).format(new Date());
    const label = state.customerName ? `${state.customerName} · ${time}` : time;
    update((h) => [{ id: crypto.randomUUID(), label, savedAt: new Date().toISOString(), lines, customerId: state.customerId, customerName: state.customerName, customerPhone: state.customerPhone }, ...h]);
    clear();
    toast(t("terminal.hold.held"), "ok");
    searchRef.current?.focus();
  }, [lines, state.customerId, state.customerName, state.customerPhone, update, clear, t]);

  function resume(id: string) {
    const target = held.find((h) => h.id === id);
    if (!target) return;
    const parked = lines.length > 0
      ? [{ id: crypto.randomUUID(), label: state.customerName || t("terminal.hold.previous"), savedAt: new Date().toISOString(), lines, customerId: state.customerId, customerName: state.customerName, customerPhone: state.customerPhone }]
      : [];
    update((h) => [...parked, ...h.filter((x) => x.id !== id)]);
    replace({ ...EMPTY_CART, lines: target.lines, customerId: target.customerId, customerName: target.customerName, customerPhone: target.customerPhone });
    setDialog(null);
    setView("cart");
  }

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (done || dialog || editing || clearing) return;
      if (e.key === "F8") { e.preventDefault(); openPay(); }
      else if (e.key === "F6") { e.preventDefault(); hold(); }
      else if (e.key === "F2" || (e.key === "/" && !(e.target instanceof HTMLInputElement) && !(e.target instanceof HTMLTextAreaElement))) { e.preventDefault(); setView("products"); searchRef.current?.focus(); searchRef.current?.select(); }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [done, dialog, editing, clearing, openPay, hold]);

  const finished = () => {
    forgetTill(till.id);
    void qc.invalidateQueries({ queryKey: ["pos-terminal", "tills"] });
  };

  return (
    <Frame
      info={<>{branch.name} · {device?.name ?? t("terminal.till")} · {me?.full_name ?? ""}</>}
      actions={<Button variant="secondary" size="sm" onClick={() => setDialog("close")}><Lock className="h-3.5 w-3.5" />{t("terminal.close.action")}</Button>}>
      {done ? (
        <SaleDone sale={done} currency={currency} onNewSale={() => setDone(null)} />
      ) : (
        <>
          <div className="flex min-h-0 flex-1 flex-col md:flex-row">
            <div className={cx("min-h-0 flex-1 flex-col md:flex", view === "products" ? "flex" : "hidden")}>
              <ProductPanel branchId={branch.id} locationId={device?.location_id ?? undefined} currency={currency} searchRef={searchRef} onAdd={add} canSetPrice={canOverride} />
            </div>
            <div className={cx("min-h-0 flex-col border-line md:flex md:w-[26rem] md:flex-none md:border-l lg:w-[30rem]", view === "cart" ? "flex flex-1" : "hidden")}>
              <CartPanel
                lines={lines} currency={currency} heldCount={held.length}
                customer={canPickCustomer ? (
                  <CustomerPicker customerId={state.customerId} customerName={state.customerName}
                    onChange={(id, name, phone) => edit((s) => ({ ...s, customerId: id, customerName: name, customerPhone: phone }))} />
                ) : null}
                onStep={(key, d) => setLines((l) => stepQuantity(l, key, d))} onEdit={setEditing} onRemove={(key) => setLines((l) => removeLine(l, key))}
                onHold={hold} onClear={() => setClearing(true)} onShowHeld={() => setDialog("held")} onPay={openPay} />
            </div>
          </div>
          <nav className="no-print grid shrink-0 grid-cols-2 border-t border-line bg-surface md:hidden" aria-label={t("terminal.view")}>
            <button type="button" onClick={() => setView("products")} className={cx("h-14 text-sm font-medium", view === "products" ? "bg-brand-soft text-brand-strong" : "text-muted")}>{t("terminal.products.title")}</button>
            <button type="button" onClick={() => setView("cart")} className={cx("h-14 text-sm font-medium", view === "cart" ? "bg-brand-soft text-brand-strong" : "text-muted")}>
              {t("terminal.cart.title")} ({itemCount(lines)}) {lines.length > 0 && text(total)}
            </button>
          </nav>
        </>
      )}

      {dialog === "pay" && (
        <PaymentDialog total={total} currency={currency} branchId={branch.id} legs={state.legs} setLegs={setLegs}
          customer={{ id: state.customerId, name: state.customerName, phone: state.customerPhone }}
          busy={sell.isPending} error={sell.error} onClose={() => setDialog(null)} onComplete={() => sell.mutate()} />
      )}
      {dialog === "held" && <HeldSales held={held} currency={currency} onResume={resume} onDelete={(id) => update((h) => h.filter((x) => x.id !== id))} onClose={() => setDialog(null)} />}
      {dialog === "close" && (
        <CloseTill till={till} currency={currency} blockedBy={lines.length > 0} heldCount={held.length} onClose={() => setDialog(null)} onClosed={finished} />
      )}
      {editingLine && (
        <LineEditor line={editingLine} currency={currency} canOverride={canOverride} onClose={() => setEditing(null)}
          onSave={(patch) => setLines((l) => patchLine(l, editingLine.key, patch))} />
      )}
      <ConfirmDialog open={clearing} onClose={() => setClearing(false)} danger title={t("terminal.cart.clearTitle")} message={t("terminal.cart.clearMessage")}
        confirmLabel={t("terminal.cart.clear")} onConfirm={() => { clear(); setClearing(false); searchRef.current?.focus(); }} />
    </Frame>
  );
}
