import { type ReactNode, useEffect, useRef, useState } from "react";

import { cx } from "./cx";

export interface MenuEntry {
  label: string;
  onSelect: () => void;
  icon?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
}

/** A small dropdown menu: opens under its trigger, closes on outside click, Escape, or choosing an item; arrow keys move. */
export function Menu({ trigger, items, align = "right", label, up }: { trigger: ReactNode; items: (MenuEntry | "separator")[]; align?: "left" | "right"; label: string; up?: boolean }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const els = [...(box.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])') ?? [])];
        const i = els.indexOf(document.activeElement as HTMLElement);
        els[(i + (e.key === "ArrowDown" ? 1 : -1) + els.length) % els.length]?.focus();
      }
    };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", down); document.removeEventListener("keydown", key); };
  }, [open]);
  return (
    <div ref={box} className="relative">
      <button type="button" aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="rounded-lg">{trigger}</button>
      {open && (
        <div role="menu" className={cx("absolute z-40 min-w-[11rem] rounded-xl border border-line bg-surface p-1 shadow-pop animate-fade", align === "right" ? "right-0" : "left-0", up ? "bottom-full mb-1" : "top-full mt-1")}>
          {items.map((it, i) => it === "separator" ? <hr key={i} className="my-1 border-line" /> : (
            <button key={it.label} role="menuitem" type="button" disabled={it.disabled} onClick={() => { setOpen(false); it.onSelect(); }}
              className={cx("flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm hover:bg-sunken disabled:opacity-50", it.danger && "text-bad")}>
              {it.icon}{it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
