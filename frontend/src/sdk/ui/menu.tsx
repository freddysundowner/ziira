import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { cx } from "./cx";

export interface MenuEntry {
  label: string;
  onSelect: () => void;
  icon?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
}

interface Place {
  top: number;
  left: number;
  minWidth: number;
  up: boolean;
}

/**
 * A small dropdown menu: opens under its trigger (above it when there is no room below), closes on outside click, Escape,
 * scrolling or choosing an item; arrow keys move. The list is drawn in a portal at the page level, so a table or card that
 * clips its contents (overflow hidden) can never cut it off.
 */
export function Menu({ trigger, items, align = "right", label, up }: { trigger: ReactNode; items: (MenuEntry | "separator")[]; align?: "left" | "right"; label: string; up?: boolean }) {
  const [open, setOpen] = useState(false);
  const [place, setPlace] = useState<Place | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open || !button.current) return;
    const r = button.current.getBoundingClientRect();
    const height = list.current?.offsetHeight ?? items.length * 36 + 8;
    const flip = up ?? (window.innerHeight - r.bottom < height + 12 && r.top > height + 12);
    const width = list.current?.offsetWidth ?? 176;
    const left = align === "right" ? Math.max(8, Math.min(r.right - width, window.innerWidth - width - 8)) : Math.min(r.left, window.innerWidth - width - 8);
    setPlace({ top: flip ? Math.max(8, r.top - height - 4) : r.bottom + 4, left, minWidth: Math.max(r.width, 176), up: flip });
  }, [open, align, up, items.length]);

  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!button.current?.contains(t) && !list.current?.contains(t)) setOpen(false);
    };
    const close = () => setOpen(false);
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setOpen(false); button.current?.focus(); }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const els = [...(list.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])') ?? [])];
        const i = els.indexOf(document.activeElement as HTMLElement);
        els[(i + (e.key === "ArrowDown" ? 1 : -1) + els.length) % els.length]?.focus();
      }
    };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);        // any scrolling container: the button moves, the list would not
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [open]);

  return (
    <>
      <button ref={button} type="button" aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => { setPlace(null); setOpen((o) => !o); }} className="rounded-lg">{trigger}</button>
      {open && createPortal(
        <div ref={list} role="menu" style={{ position: "fixed", top: place?.top ?? -9999, left: place?.left ?? -9999, minWidth: place?.minWidth, visibility: place ? "visible" : "hidden" }}
          className="z-[70] max-h-[70vh] overflow-y-auto rounded-xl border border-line bg-surface p-1 shadow-pop animate-fade">
          {items.map((it, i) => it === "separator" ? <hr key={i} className="my-1 border-line" /> : (
            <button key={it.label} role="menuitem" type="button" disabled={it.disabled} onClick={() => { setOpen(false); it.onSelect(); }}
              className={cx("flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm hover:bg-sunken focus:bg-sunken disabled:opacity-50", it.danger && "text-bad")}>
              {it.icon}{it.label}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </>
  );
}
