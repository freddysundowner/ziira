import { Lock } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  api, Button, ConfirmDialog, cx, toast, unwrap, useCan, useMutation, useQueryClient, useSession, useTranslation, type Schemas,
} from "@/sdk";

import type { BranchInfo } from "../branches";
import {
  addItem, type CartLine, cartProblem, cartTotal, EMPTY_CART, fingerprint, itemCount, newLeg, patchLine, paySummary, removeLine, stepQuantity, text, toSaleLines, toSalePayments,
  type CatalogItem,
} from "../cart";
import { forgetTill, useCart, useHeld } from "../hooks";
import type { useTerminalCache } from "../offline/cache";
import { isUnreachable, reportReachable } from "../offline/connectivity";
import { addSale, serverOffsetMs, syncNow } from "../offline/controller";
import { useOnline, useOutbox } from "../offline/hooks";
import { buildOfflineSale } from "../offline/localSale";
import { branchKey, forgetSnapshot } from "../offline/snapshot";
import { CartPanel } from "./CartPanel";
import { CloseTill } from "./CloseTill";
import { CustomerPicker } from "./CustomerPicker";
import { Frame } from "./Frame";
import { HeldSales } from "./HeldSales";
import { LineEditor } from "./LineEditor";
import { PaymentDialog } from "./PaymentDialog";
import { ProductPanel } from "./ProductPanel";
import { type DoneView, SaleDone } from "./SaleDone";
import { SyncBanner } from "./SyncBanner";

type Dialog = "pay" | "held" | "close" | null;

/** The terminal proper: products on the left, the cart on the right, payment and closing in dialogs. */
export function Selling({ till, device, branch, cacheState }: {
  till: Schemas["TillOut"]; device: Schemas["DeviceOut"] | undefined; branch: BranchInfo; cacheState: ReturnType<typeof useTerminalCache>;
}) {
  const { t } = useTranslation("pos");
  const qc = useQueryClient();
  const { me, enabledUnits } = useSession();
  const canOverride = useCan("price.override");
  const canPickCustomer = useCan("customers.view") && enabledUnits.has("crm");
  const currency = branch.currency;

  const online = useOnline();
  const outbox = useOutbox();
  const { cache } = cacheState;
  const offline = !online;
  const cannotSaveOffline = offline && !outbox.storageOk;
  const reserved = useMemo(() => outbox.reserved(branch.id), [outbox, branch.id]);
  const waitingHere = outbox.entries.filter((e) => e.tillId === till.id && e.state !== "done").length;

  const { state, edit, setLegs, setAttempt, clear, replace } = useCart(till.id);
  const { held, hold: holdSale, release } = useHeld(till.id, online);
  const [view, setView] = useState<"products" | "cart">("products");
  const [dialog, setDialog] = useState<Dialog>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);
  const [done, setDone] = useState<DoneView | null>(null);
  const [closeGuard, setCloseGuard] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const lines = state.lines;
  const total = cartTotal(lines);
  const canPay = lines.length > 0 && cartProblem(lines) === null;
  const editingLine = lines.find((l) => l.key === editing);

  const setLines = useCallback((change: (lines: CartLine[]) => CartLine[]) => edit((s) => ({ ...s, lines: change(s.lines) })), [edit]);
  const add = (item: CatalogItem) => setLines((l) => addItem(l, item));

  // Keep the sale on this device to be sent later. The same id as an online try would have used, so a sale whose
  // answer was lost on the way is still recorded once.
  const keepOnDevice = async (id: string): Promise<DoneView> => {
    const entry = await addSale({
      localId: id, tillId: till.id, branchId: branch.id, userId: me?.user_id ?? "", deviceId: device?.id ?? till.device_id, deviceCode: device?.code ?? "",
      madeAt: Date.now(), offsetMs: serverOffsetMs(), currency,
      build: (number) => {
        const built = buildOfflineSale({
          localId: id, tillId: till.id, branchId: branch.id, userId: me?.user_id ?? "", number, madeAt: Date.now(), offsetMs: serverOffsetMs(), currency,
          lines, legs: state.legs, customerId: state.customerId, customerName: state.customerName, cashierName: me?.full_name ?? "",
          header: cache?.receipt?.header ?? [branch.name], footer: cache?.receipt?.footer ?? [],
          labels: {
            title: t("terminal.sync.receiptTitle"), provisional: t("terminal.sync.receiptProvisional"), date: t("terminal.sync.receiptDate"),
            servedBy: t("terminal.sync.receiptServedBy"), customer: t("terminal.sync.receiptCustomer"), subtotal: t("terminal.sync.receiptSubtotal"),
            discount: t("terminal.sync.receiptDiscount"), total: t("terminal.sync.receiptTotal"),
          },
        });
        return { total: built.total, op: built.op, lines: built.lines, customerName: state.customerName, receipt: built.receipt };
      },
    });
    return { kind: "saved", entry, change: text(paySummary(total, state.legs.filter((l) => Number(l.amount) > 0)).change) };
  };
  // Storage can fail (full disk, blocked): say so plainly; the cart is untouched and nothing was recorded.
  const saveOffline = (id: string): Promise<DoneView> => keepOnDevice(id).catch((error: Error) => {
    throw new Error(t("terminal.sync.saveFailed", { reason: error.message }));
  });

  // One id per distinct sale: a retry of the same content (after a dropped connection) is recorded once; a changed cart gets a new id.
  const sell = useMutation({
    meta: { silent: true },
    networkMode: "always",                  // runs with no connection: the sale is then kept on this device
    mutationFn: async (): Promise<DoneView> => {
      const print = fingerprint(state);
      const attempt = state.attempt?.fingerprint === print ? state.attempt : { id: crypto.randomUUID(), fingerprint: print };
      setAttempt(attempt);
      if (offline) return saveOffline(attempt.id);
      try {
        const sale = await unwrap(api.POST("/api/v1/pos/sales", {
          body: { till_session_id: till.id, lines: toSaleLines(lines), payments: toSalePayments(state.legs), customer_id: state.customerId || null, local_id: attempt.id },
        }));
        return { kind: "sent", sale };
      } catch (error) {
        // The connection dropped: the sale may or may not have reached the server. Keeping it with the same id is safe either way.
        if (!isUnreachable(error)) throw error;
        reportReachable(false);
        return saveOffline(attempt.id);
      }
    },
    onSuccess: (result) => {
      clear();
      setDialog(null);
      setView("products");
      setDone(result);
      void qc.invalidateQueries({ queryKey: ["pos-terminal", "catalog"] });
    },
  });

  const openPay = useCallback(() => {
    if (!canPay) return;
    if (state.legs.length === 0) setLegs(() => [newLeg("cash", total)]);
    sell.reset();
    setDialog("pay");
  }, [canPay, state.legs.length, total, setLegs, sell]);

  const heldOf = (label: string): Parameters<typeof holdSale>[0] => ({
    id: crypto.randomUUID(), label, savedAt: new Date().toISOString(), lines, customerId: state.customerId, customerName: state.customerName, customerPhone: state.customerPhone,
  });
  const hold = useCallback(() => {
    if (lines.length === 0) return;
    const time = new Intl.DateTimeFormat(undefined, { timeStyle: "short" }).format(new Date());
    holdSale(heldOf(state.customerName ? `${state.customerName} · ${time}` : time));
    clear();
    toast(t("terminal.hold.held"), "ok");
    searchRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- heldOf reads the same values listed here
  }, [lines, state.customerId, state.customerName, state.customerPhone, holdSale, clear, t]);

  const rateOf = useMemo(() => new Map((cache?.items ?? []).map((i) => [i.product_id, String(i.vat_rate)])), [cache]);
  function resume(id: string) {
    const target = held.find((h) => h.id === id);
    if (!target) return;
    if (lines.length > 0) holdSale(heldOf(state.customerName || t("terminal.hold.previous")));
    release(id, "resume");
    const resumed = target.lines.map((l) => ({ ...l, vatRate: l.vatRate !== "0" ? l.vatRate : (rateOf.get(l.productId) ?? "0") }));
    replace({ ...EMPTY_CART, lines: resumed, customerId: target.customerId, customerName: target.customerName, customerPhone: target.customerPhone });
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
    // Do not let a page loaded later without a connection believe this till is still open.
    void forgetSnapshot(branchKey(me?.user_id ?? "", branch.id)).then(() => qc.invalidateQueries({ queryKey: ["pos-terminal", "branch"] }));
  };

  // Browsers may clear a site's data when space runs short; ask them not to (the sales waiting must survive).
  useEffect(() => { void navigator.storage?.persist?.().catch(() => undefined); }, []);

  const askToClose = () => {
    if (offline) { toast(t("terminal.sync.closeOffline"), "warn"); return; }
    if (waitingHere > 0) { void syncNow(true); setCloseGuard(true); return; }
    setDialog("close");
  };

  return (
    <Frame
      info={<>{branch.name} · {device?.name ?? t("terminal.till")} · {me?.full_name ?? ""}</>}
      actions={<Button variant="secondary" size="sm" onClick={askToClose}><Lock className="h-3.5 w-3.5" />{t("terminal.close.action")}</Button>}>
      <SyncBanner />
      {done ? (
        <SaleDone view={done} currency={currency} onNewSale={() => setDone(null)} />
      ) : (
        <>
          <div className="flex min-h-0 flex-1 flex-col md:flex-row">
            <div className={cx("min-h-0 flex-1 flex-col md:flex", view === "products" ? "flex" : "hidden")}>
              <ProductPanel branchId={branch.id} locationId={device?.location_id ?? undefined} currency={currency} searchRef={searchRef} onAdd={add} canSetPrice={canOverride}
                cache={cache} online={online} reserved={reserved} />
            </div>
            <div className={cx("min-h-0 flex-col border-line md:flex md:w-[26rem] md:flex-none md:border-l lg:w-[30rem]", view === "cart" ? "flex flex-1" : "hidden")}>
              <CartPanel
                lines={lines} currency={currency} heldCount={held.length}
                customer={canPickCustomer ? (
                  <CustomerPicker customerId={state.customerId} customerName={state.customerName} online={online} saved={cache?.customers ?? []}
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
          busy={sell.isPending} error={sell.error} onClose={() => setDialog(null)} onComplete={() => sell.mutate()}
          offline={offline} savedAccounts={cache?.accounts ?? []} cannotSaveOffline={cannotSaveOffline} />
      )}
      {dialog === "held" && <HeldSales held={held} currency={currency} onResume={resume} onDelete={(id) => release(id, "discard")} onClose={() => setDialog(null)} />}
      {dialog === "close" && (
        <CloseTill till={till} currency={currency} blockedBy={lines.length > 0} heldCount={held.length} onClose={() => setDialog(null)} onClosed={finished} />
      )}
      {editingLine && (
        <LineEditor line={editingLine} currency={currency} canOverride={canOverride} online={online} savedReasons={cache?.reasons.price_override} onClose={() => setEditing(null)}
          onSave={(patch) => setLines((l) => patchLine(l, editingLine.key, patch))} />
      )}
      <ConfirmDialog open={closeGuard} onClose={() => setCloseGuard(false)} danger title={t("terminal.sync.closeTitle")}
        message={t("terminal.sync.closeMessage", { count: waitingHere })} confirmLabel={t("terminal.sync.closeAnyway")}
        onConfirm={() => { setCloseGuard(false); setDialog("close"); }} />
      <ConfirmDialog open={clearing} onClose={() => setClearing(false)} danger title={t("terminal.cart.clearTitle")} message={t("terminal.cart.clearMessage")}
        confirmLabel={t("terminal.cart.clear")} onConfirm={() => { clear(); setClearing(false); searchRef.current?.focus(); }} />
    </Frame>
  );
}
