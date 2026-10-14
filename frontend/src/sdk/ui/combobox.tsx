import { Check, ChevronsUpDown, Search } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { cx } from "./cx";
import { useDebounced } from "./hooks";
import { Spinner } from "./feedback";

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
  const listId = useId();
  const q = useDebounced(text, 250);

  useEffect(() => {
    if (!open || !search) return;
    let cancelled = false;
    setBusy(true);
    search(q).then((r) => { if (!cancelled) setFound(r); }).catch(() => { if (!cancelled) setFound([]); }).finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [q, open, search]);

  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", down);
    return () => document.removeEventListener("mousedown", down);
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
      <button id={id} type="button" disabled={disabled} role="combobox" aria-expanded={open} aria-controls={listId} aria-invalid={invalid || undefined}
        onClick={() => { setOpen((o) => !o); setActive(0); }}
        className={cx("flex h-9 w-full items-center justify-between rounded-lg border bg-surface px-3 text-left text-sm disabled:bg-sunken", invalid ? "border-bad" : "border-line hover:border-muted/50")}>
        <span className={cx("truncate", !shownLabel && "text-muted/70")}>{shownLabel || placeholder}</span>
        <ChevronsUpDown className="h-4 w-4 shrink-0 text-muted" />
      </button>
      {open && (
        <div className="absolute z-40 mt-1 w-full min-w-[14rem] rounded-xl border border-line bg-surface shadow-pop animate-fade">
          <div className="relative border-b border-line p-2">
            <Search className="pointer-events-none absolute left-4 top-4 h-4 w-4 text-muted" />
            <input autoFocus value={text} onChange={(e) => { setText(e.target.value); setActive(0); }} placeholder="Type to search" aria-label="Search"
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, list.length - 1)); }
                else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
                else if (e.key === "Enter") { e.preventDefault(); if (list[active]) choose(list[active]); }
                else if (e.key === "Escape") setOpen(false);
              }}
              className="h-8 w-full rounded-md bg-sunken pl-8 pr-2 text-sm" />
            {busy && <Spinner className="absolute right-4 top-4 text-muted" />}
          </div>
          <ul id={listId} role="listbox" className="max-h-60 overflow-y-auto p-1">
            {clearable && value && <li><button type="button" className="w-full rounded-lg px-2.5 py-2 text-left text-sm text-muted hover:bg-sunken" onClick={() => choose(undefined)}>Clear</button></li>}
            {list.length === 0 && !busy && <li className="px-3 py-4 text-center text-sm text-muted">No results</li>}
            {list.map((o, i) => (
              <li key={o.value} role="option" aria-selected={o.value === value}>
                <button type="button" onMouseEnter={() => setActive(i)} onClick={() => choose(o)}
                  className={cx("flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-sm", i === active && "bg-sunken")}>
                  <span className="min-w-0"><span className="block truncate">{o.label}</span>{o.hint && <span className="block truncate text-xs text-muted">{o.hint}</span>}</span>
                  {o.value === value && <Check className="h-4 w-4 shrink-0 text-brand" />}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
