import { Check, ChevronsUpDown, Search } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { cx } from "./cx";
import { useDebounced } from "./hooks";
import { Spinner } from "./feedback";

const list_len = (a?: unknown[], b?: unknown[]) => (a?.length ?? 0) + (b?.length ?? 0);

export interface Option {
  value: string;
  label: string;
  hint?: string;
}

/**
 * Pick one item from a list that may be long (customers, suppliers, products). Give it `options` for a short list, or
 * `search` to look up on the server as the person types.
 */
export function Combobox({ value, onChange, options, search, selectedLabel, placeholder = "Select…", disabled, invalid, id, clearable }: {
  value: string; onChange: (value: string, option?: Option) => void; options?: Option[];
  search?: (text: string) => Promise<Option[]>; selectedLabel?: string; placeholder?: string; disabled?: boolean; invalid?: boolean; id?: string; clearable?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [found, setFound] = useState<Option[]>([]);
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ top: number; left: number; width: number; maxHeight: number } | null>(null);
  const listId = useId();
  const optionCount = list_len(options, found);
  const q = useDebounced(text, 250);

  useEffect(() => {
    if (!open || !search) return;
    let cancelled = false;
    setBusy(true);
    search(q).then((r) => { if (!cancelled) setFound(r); }).catch(() => { if (!cancelled) setFound([]); }).finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [q, open, search]);

  /** The list is drawn in a portal at page level, so a dialog, drawer or card that scrolls or clips its contents can never cut it off. */
  useLayoutEffect(() => {
    if (!open || !trigger.current) return;
    const place = () => {
      const r = trigger.current!.getBoundingClientRect();
      const width = Math.max(r.width, 224);
      const wanted = Math.min(panel.current?.offsetHeight ?? 360, 360);
      const below = window.innerHeight - r.bottom - 12;
      const above = r.top - 12;
      const flip = below < Math.min(wanted, 220) && above > below;
      const maxHeight = Math.max(160, Math.min(flip ? above : below, 420));
      const left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8));
      setPlace({ top: flip ? Math.max(8, r.top - Math.min(wanted, maxHeight) - 4) : r.bottom + 4, left, width, maxHeight });
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open, optionCount]);

  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!box.current?.contains(t) && !panel.current?.contains(t)) setOpen(false);
    };
    const away = (e: Event) => { if (!panel.current?.contains(e.target as Node)) setOpen(false); };     // the trigger moved: close rather than float away from it
    document.addEventListener("mousedown", down);
    window.addEventListener("scroll", away, true);
    return () => { document.removeEventListener("mousedown", down); window.removeEventListener("scroll", away, true); };
  }, [open]);

  const list = search ? found : (options ?? []).filter((o) => `${o.label} ${o.hint ?? ""}`.toLowerCase().includes(text.trim().toLowerCase()));
  const current = [...(options ?? []), ...found].find((o) => o.value === value);
  const shownLabel = current?.label ?? selectedLabel ?? "";

  function choose(o: Option | undefined) {
    onChange(o?.value ?? "", o);
    setOpen(false);
    setText("");
  }

  return (
    <div ref={box} className="relative">
      <button ref={trigger} id={id} type="button" disabled={disabled} role="combobox" aria-label={id ? undefined : shownLabel ? `${placeholder}: ${shownLabel}` : placeholder} aria-expanded={open} aria-controls={listId} aria-invalid={invalid || undefined}
        onClick={() => { setOpen((o) => !o); setActive(0); }}
        className={cx("flex h-9 w-full min-w-0 items-center justify-between gap-2 rounded-lg border bg-surface px-3 text-left text-sm disabled:bg-sunken", invalid ? "border-bad" : "border-line hover:border-muted/50")}>
        <span className={cx("min-w-0 flex-1 truncate", !shownLabel && "text-muted")}>{shownLabel || placeholder}</span>
        <ChevronsUpDown className="h-4 w-4 shrink-0 text-muted" />
      </button>
      {open && createPortal(
        <div ref={panel} style={{ position: "fixed", top: place?.top ?? -9999, left: place?.left ?? -9999, width: place?.width, visibility: place ? "visible" : "hidden" }}
          className="z-[80] flex flex-col rounded-xl border border-line bg-surface shadow-pop animate-fade">
          <div className="relative border-b border-line p-2">
            <Search className="pointer-events-none absolute left-4 top-4 h-4 w-4 text-muted" />
            <input autoFocus value={text} onChange={(e) => { setText(e.target.value); setActive(0); }} placeholder="Type to search" aria-label="Search"
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, list.length - 1)); }
                else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
                else if (e.key === "Enter") { e.preventDefault(); if (list[active]) choose(list[active]); }
                else if (e.key === "Escape") { e.stopPropagation(); setOpen(false); trigger.current?.focus(); }
              }}
              className="h-8 w-full rounded-md bg-sunken pl-8 pr-2 text-sm" />
            {busy && <Spinner className="absolute right-4 top-4 text-muted" />}
          </div>
          <ul id={listId} role="listbox" style={{ maxHeight: place ? Math.max(120, place.maxHeight - 64) : 240 }} className="overflow-y-auto p-1">
            {clearable && value && <li><button type="button" className="w-full rounded-lg px-2.5 py-2 text-left text-sm text-muted hover:bg-sunken" onClick={() => choose(undefined)}>Clear</button></li>}
            {list.length === 0 && !busy && <li className="px-3 py-4 text-center text-sm text-muted">No results</li>}
            {list.map((o, i) => (
              <li key={o.value} role="option" aria-selected={o.value === value}>
                <button type="button" onMouseEnter={() => setActive(i)} onClick={() => choose(o)}
                  className={cx("flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-sm", i === active && "bg-sunken")}>
                  <span className="min-w-0"><span className="block truncate">{o.label}</span>{o.hint && <span className="block truncate text-xs text-muted">{o.hint}</span>}</span>
                  {o.value === value && <Check className="h-4 w-4 shrink-0 text-brand-strong" />}
                </button>
              </li>
            ))}
          </ul>
        </div>,
        document.body,
      )}
    </div>
  );
}
