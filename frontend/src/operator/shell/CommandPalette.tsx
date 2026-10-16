import { CornerDownLeft, FileSearch, Search as SearchIcon } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";

import { cx, Spinner, useDebounced, useTranslation } from "@/sdk";

import { groupHits, type Hit, matchPages, MIN_QUERY, moveIndex, pageHits } from "../helpers/search";
import { NAV_GROUPS } from "../nav";
import { useSearch } from "./data";

const ORDER = ["page", "subscriber", "invoice", "plan", "licence", "operator"] as const;

interface Props {
  open: boolean;
  onClose: () => void;
  permissions: readonly string[];
  missingFeatures: readonly string[];
}

/**
 * The search box (Ctrl/Cmd + K, or "/"): screens of the console are found on this device; subscribers, invoices, plans,
 * licences and operators come from the server (which shows only what the role may see). Arrow keys move, Enter opens,
 * Escape closes.
 */
export function CommandPalette({ open, onClose, permissions, missingFeatures }: Props) {
  const { t } = useTranslation("operator");
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const typed = useDebounced(text.trim(), 250);
  const server = useSearch(open ? typed : "");

  const pages = useMemo(
    () => pageHits(NAV_GROUPS, permissions, missingFeatures, (id) => t(`nav.i.${id}`), (key) => t(key)),
    [permissions, missingFeatures, t],
  );
  const all = useMemo<Hit[]>(() => {
    const local = text.trim().length < MIN_QUERY ? pages.slice(0, 7) : matchPages(pages, text);
    return [...local, ...(server.data ?? []).map((h): Hit => ({ ...h, kind: h.kind }))];
  }, [pages, text, server.data]);
  const groups = groupHits(all, ORDER);
  const flat = groups.flatMap((g) => g.hits);

  useEffect(() => {
    if (!open) return;
    setText("");
    setIndex(0);
    const before = document.activeElement as HTMLElement | null;
    input.current?.focus();
    return () => before?.focus?.();
  }, [open]);
  useEffect(() => setIndex(0), [text, server.data]);
  useEffect(() => {
    document.getElementById(`hit-${index}`)?.scrollIntoView?.({ block: "nearest" });
  }, [index]);

  if (!open) return null;
  const go = (hit: Hit | undefined) => {
    if (!hit) return;
    onClose();
    navigate(hit.to);
  };
  const key = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setIndex((i) => moveIndex(i, 1, flat.length)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIndex((i) => moveIndex(i, -1, flat.length)); }
    else if (e.key === "Enter") { e.preventDefault(); go(flat[index]); }
    else if (e.key === "Escape") { e.stopPropagation(); onClose(); }
  };
  const searching = text.trim().length >= MIN_QUERY && (typed !== text.trim() || server.isFetching);
  let position = -1;
  let body: ReactNode;
  if (flat.length === 0) {
    body = (
      <div className="flex flex-col items-center gap-2 px-4 py-10 text-center text-sm text-muted">
        {searching ? <Spinner /> : <FileSearch className="h-6 w-6" aria-hidden />}
        <p>{searching ? t("shell.search.searching") : text.trim().length < MIN_QUERY ? t("shell.search.hint") : t("shell.search.none", { text: text.trim() })}</p>
        {server.isError && <p className="text-bad">{t("shell.search.failed")}</p>}
      </div>
    );
  } else {
    body = groups.map((g) => (
      <div key={g.kind} role="group" aria-label={t(`shell.search.kinds.${g.kind}`)}>
        <p className="px-4 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-muted">{t(`shell.search.kinds.${g.kind}`)}</p>
        {g.hits.map((hit) => {
          position += 1;
          const mine = position;
          const Icon = hit.icon;
          return (
            <div key={`${hit.kind}:${hit.id}`} id={`hit-${mine}`} role="option" aria-selected={mine === index} onMouseMove={() => setIndex(mine)} onClick={() => go(hit)}
              className={cx("mx-2 flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2", mine === index ? "bg-brand-soft" : "hover:bg-sunken")}>
              {Icon && <Icon className="h-4 w-4 shrink-0 text-muted" aria-hidden />}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{hit.title}</span>
                {hit.subtitle && <span className="block truncate text-xs text-muted">{hit.subtitle}</span>}
              </span>
              {mine === index && <CornerDownLeft className="h-3.5 w-3.5 text-muted" aria-hidden />}
            </div>
          );
        })}
      </div>
    ));
  }
  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-start justify-center bg-black/50 p-3 pt-[10vh] animate-fade" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label={t("shell.search.title")} className="flex max-h-[70vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl bg-surface shadow-pop animate-rise motion-reduce:animate-none" onKeyDown={key}>
        <div className="flex items-center gap-2 border-b border-line px-4">
          <SearchIcon className="h-4 w-4 text-muted" aria-hidden />
          <input ref={input} value={text} onChange={(e) => setText(e.target.value)} role="combobox" aria-expanded="true" aria-controls="search-results" aria-activedescendant={flat.length ? `hit-${index}` : undefined}
            aria-autocomplete="list" autoComplete="off" spellCheck={false} maxLength={80} placeholder={t("shell.search.placeholder")} aria-label={t("shell.search.title")}
            className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-muted" />
          <kbd className="hidden rounded border border-line px-1.5 py-0.5 text-[11px] text-muted sm:block">Esc</kbd>
        </div>
        <div id="search-results" role="listbox" aria-label={t("shell.search.title")} className="overflow-y-auto pb-2">{body}</div>
      </div>
    </div>,
    document.body,
  );
}
