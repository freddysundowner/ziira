import { useCallback, useEffect, useRef, useState } from "react";

import { type CartState, EMPTY_CART, type HeldSale, keepCollected, parseCart, parseHeld } from "./cart";
import { readJson, writeJson } from "./storage";

const cartKey = (tillId: string) => `ziira.pos.cart.${tillId}`;
const heldKey = (tillId: string) => `ziira.pos.held.${tillId}`;

/** The cart of one till session, written to the browser on every change so nothing is lost on a refresh or a dropped connection. */
export function useCart(tillId: string) {
  const [state, setState] = useState<CartState>(() => parseCart(readJson<unknown>(cartKey(tillId), null)));
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    writeJson(cartKey(tillId), state.lines.length || state.legs.length ? state : null);
  }, [state, tillId]);

  /** Change the lines or customer: payments not yet collected are dropped, as their amounts no longer fit. */
  const edit = useCallback((change: (s: CartState) => CartState) => setState((s) => {
    const next = change(s);
    return { ...next, legs: keepCollected(next.legs) };
  }), []);
  /** Change the payment legs only. */
  const setLegs = useCallback((change: (legs: CartState["legs"]) => CartState["legs"]) => setState((s) => ({ ...s, legs: change(s.legs) })), []);
  const setAttempt = useCallback((attempt: CartState["attempt"]) => setState((s) => ({ ...s, attempt })), []);
  const clear = useCallback(() => setState(EMPTY_CART), []);
  const replace = useCallback((next: CartState) => setState(next), []);
  return { state, edit, setLegs, setAttempt, clear, replace };
}

/** Sales put on hold at this till (kept in this browser). */
export function useHeld(tillId: string) {
  const [held, setHeld] = useState<HeldSale[]>(() => parseHeld(readJson<unknown>(heldKey(tillId), [])));
  const update = useCallback((change: (h: HeldSale[]) => HeldSale[]) => setHeld((h) => {
    const next = change(h);
    writeJson(heldKey(tillId), next.length ? next : null);
    return next;
  }), [tillId]);
  return { held, update };
}

export function forgetTill(tillId: string): void {
  writeJson(cartKey(tillId), null);
  writeJson(heldKey(tillId), null);
}

/** True while the browser reports no connection. */
export function useOnline(): boolean {
  const [online, setOnline] = useState(() => typeof navigator === "undefined" || navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true), off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, []);
  return online;
}
