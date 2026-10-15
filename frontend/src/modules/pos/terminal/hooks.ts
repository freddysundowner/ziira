import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError, unwrap } from "@/sdk";

import { type CartState, EMPTY_CART, type HeldSale, keepCollected, parseCart, parseHeld } from "./cart";
import { applyReconciled, reconcileHeld, toServerBody } from "./offline/held";
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

const goneKey = (tillId: string) => `ziira.pos.held-gone.${tillId}`;

/**
 * Sales put on hold at this till. They are kept in this browser (so they survive a refresh and work without a connection)
 * and at the server (so they survive a cleared browser): held while offline, a sale is sent to the server when the
 * connection returns; resumed or discarded, the server is told, now or later.
 */
export function useHeld(tillId: string, online: boolean) {
  const [held, setHeld] = useState<HeldSale[]>(() => parseHeld(readJson<unknown>(heldKey(tillId), [])));
  const latest = useRef(held);
  latest.current = held;
  const update = useCallback((change: (h: HeldSale[]) => HeldSale[]) => setHeld((h) => {
    const next = change(h);
    writeJson(heldKey(tillId), next.length ? next : null);
    return next;
  }), [tillId]);

  const gone = useCallback(() => new Set(readJson<string[]>(goneKey(tillId), [])), [tillId]);
  const remember = useCallback((ids: Set<string>) => writeJson(goneKey(tillId), ids.size ? [...ids] : null), [tillId]);

  /** Tell the server, best effort; whatever it could not be told stays in the list to try again. */
  const tell = useCallback(async (id: string, action: "resume" | "discard"): Promise<boolean> => {
    try {
      const path = action === "resume" ? "/api/v1/pos/held/{held_id}/resume" : "/api/v1/pos/held/{held_id}/discard";
      await unwrap(api.POST(path, { params: { path: { held_id: id } } }));
      return true;
    } catch (error) {
      return error instanceof ApiError && (error.status === 404 || error.status === 409);       // already gone at the server
    }
  }, []);

  // Sales resumed or discarded here: never sent to the server afterwards, and thrown away there if a send was already on its way.
  const released = useRef(new Set<string>());
  const upload = useCallback(async (h: HeldSale) => {
    if (released.current.has(h.id)) return;
    try {
      await unwrap(api.POST("/api/v1/pos/tills/{till_id}/held", { params: { path: { till_id: tillId } }, body: toServerBody(h) }));
      if (released.current.has(h.id)) await tell(h.id, "discard");
      else update((list) => list.map((x) => (x.id === h.id ? { ...x, remote: true } : x)));
    } catch {
      // stays here; sent on the next round
    }
  }, [tillId, update, tell]);

  /** Bring this device and the server together (whenever there is a connection). */
  const sync = useCallback(async () => {
    try {
      const pending = gone();
      for (const id of [...pending]) if (await tell(id, "discard")) pending.delete(id);
      remember(pending);
      const server = await unwrap(api.GET("/api/v1/pos/tills/{till_id}/held", { params: { path: { till_id: tillId } } }));
      const changes = reconcileHeld(latest.current, server, pending);
      update((list) => applyReconciled(list, changes));
      for (const h of changes.upload) await upload(h);
    } catch {
      // no answer: try again next time
    }
  }, [tillId, gone, remember, tell, update, upload]);

  useEffect(() => { if (online) void sync(); }, [online, sync]);

  const hold = useCallback((h: HeldSale) => {
    update((list) => [h, ...list]);
    if (online) void upload(h);
  }, [update, online, upload]);

  /** The sale leaves the list (resumed to the screen or thrown away). */
  const release = useCallback((id: string, action: "resume" | "discard") => {
    released.current.add(id);
    update((list) => list.filter((h) => h.id !== id));
    // The server may already have a copy (an upload could be on its way), so it is always told; "not found" is fine.
    const pending = gone();
    pending.add(id);
    remember(pending);
    if (online) void tell(id, action).then((ok) => { if (ok) { const left = gone(); left.delete(id); remember(left); } });
  }, [update, gone, remember, online, tell]);

  return { held, update, hold, release };
}

export function forgetTill(tillId: string): void {
  writeJson(cartKey(tillId), null);
  writeJson(heldKey(tillId), null);
  writeJson(goneKey(tillId), null);
}
