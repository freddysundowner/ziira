import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { cx } from "./cx";
import { EmptyState, ErrorState, SkeletonRows } from "./feedback";
import { Input } from "./forms";

export interface Column<Row> {
  header: string;
  cell: (row: Row) => ReactNode;
  /** Makes the column sortable by this value. */
  sortValue?: (row: Row) => string | number | null | undefined;
  align?: "left" | "right";
  /** Hide on screens narrower than this (the row stays readable on a phone). */
  hideBelow?: "sm" | "md" | "lg";
  className?: string;
}

const HIDE = { sm: "hidden sm:table-cell", md: "hidden md:table-cell", lg: "hidden lg:table-cell" };

export interface DataTableProps<Row> {
  rows: readonly Row[] | undefined;
  columns: Column<Row>[];
  rowKey: (row: Row) => string;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** Shown when there are no rows. */
  empty: { title: string; hint?: string; action?: ReactNode };
  /** Clicking a row goes here. */
  rowHref?: (row: Row) => string;
  /** Adds a search box that filters the rows on screen by this text. */
  searchText?: (row: Row) => string;
  searchPlaceholder?: string;
  /** Extra controls shown beside the search box. */
  toolbar?: ReactNode;
  /** Rows per page on screen (client side). Omit to show all. */
  pageSize?: number;
  footer?: ReactNode;
  dense?: boolean;
}

/**
 * The one table: loading skeleton, error with retry, empty state, search, sort, paging, clickable rows, and a horizontal
 * scroll on small screens. Server-paged lists pass their page as `rows` and render <Pager> as `footer`.
 */
export function DataTable<Row>({ rows, columns, rowKey, loading, error, onRetry, empty, rowHref, searchText, searchPlaceholder = "Search", toolbar, pageSize, footer, dense }: DataTableProps<Row>) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ col: number; dir: 1 | -1 } | null>(null);
  const [page, setPage] = useState(0);

  const shown = useMemo(() => {
    let out = [...(rows ?? [])];
    const q = query.trim().toLowerCase();
    if (q && searchText) out = out.filter((r) => searchText(r).toLowerCase().includes(q));
    if (sort) {
      const get = columns[sort.col]?.sortValue;
      if (get) out.sort((a, b) => {
        const x = get(a), y = get(b);
        if (x == null && y == null) return 0;
        if (x == null) return 1;
        if (y == null) return -1;
        return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true })) * sort.dir;
      });
    }
    return out;
  }, [rows, query, sort, columns, searchText]);

  useEffect(() => setPage(0), [query, sort, rows?.length]);
  const pages = pageSize ? Math.max(1, Math.ceil(shown.length / pageSize)) : 1;
  const visible = pageSize ? shown.slice(page * pageSize, (page + 1) * pageSize) : shown;
  const pad = dense ? "py-1.5" : "py-2.5";

  let body: ReactNode;
  if (error) body = <ErrorState message={error} onRetry={onRetry} />;
  else if (loading && !rows) body = <SkeletonRows />;
  else if (shown.length === 0) {
    body = query ? <EmptyState title="Nothing matches your search" hint="Try a different word." /> : <EmptyState {...empty} />;
  } else {
    body = (
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line bg-sunken/60 text-[11px] uppercase tracking-[0.06em] text-muted">
            <tr>
              {columns.map((c, i) => {
                const active = sort?.col === i;
                return (
                  <th key={c.header} scope="col" aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : undefined}
                    className={cx("px-4 py-3 font-semibold", c.align === "right" && "text-right", c.hideBelow && HIDE[c.hideBelow])}>
                    {c.sortValue ? (
                      <button className="inline-flex items-center gap-1 uppercase tracking-[0.06em] hover:text-ink" onClick={() => setSort(active && sort.dir === -1 ? null : { col: i, dir: active ? -1 : 1 })}>
                        {c.header}{active && (sort.dir === 1 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
                      </button>
                    ) : c.header}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {visible.map((row) => (
              <tr key={rowKey(row)} className={cx(rowHref && "cursor-pointer hover:bg-sunken/60")}
                onClick={rowHref ? (e) => { if (!(e.target as HTMLElement).closest("a,button,input,select")) navigate(rowHref(row)); } : undefined}>
                {columns.map((c) => (
                  <td key={c.header} className={cx("px-4", pad, c.align === "right" && "tnum text-right", c.hideBelow && HIDE[c.hideBelow], c.className)}>{c.cell(row)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface shadow-card">
      {(searchText || toolbar) && (
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          {searchText && (
            <div className="relative min-w-[200px] max-w-sm flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted" />
              <Input aria-label={searchPlaceholder} className="pl-8" placeholder={searchPlaceholder} value={query} onChange={(e) => setQuery(e.target.value)} />
            </div>
          )}
          {toolbar}
        </div>
      )}
      {body}
      {pageSize && pages > 1 && !error && (
        <div className="flex items-center justify-between border-t border-line px-4 py-2 text-xs text-muted">
          <span>{page * pageSize + 1}–{Math.min(shown.length, (page + 1) * pageSize)} of {shown.length}</span>
          <PageButtons canPrev={page > 0} canNext={page < pages - 1} onPrev={() => setPage(page - 1)} onNext={() => setPage(page + 1)} />
        </div>
      )}
      {footer}
    </div>
  );
}

function PageButtons({ canPrev, canNext, onPrev, onNext }: { canPrev: boolean; canNext: boolean; onPrev: () => void; onNext: () => void }) {
  const cls = "inline-flex h-8 w-8 items-center justify-center rounded-lg border border-line hover:bg-sunken disabled:opacity-40";
  return (
    <div className="flex gap-1">
      <button aria-label="Previous page" className={cls} disabled={!canPrev} onClick={onPrev}><ChevronLeft className="h-4 w-4" /></button>
      <button aria-label="Next page" className={cls} disabled={!canNext} onClick={onNext}><ChevronRight className="h-4 w-4" /></button>
    </div>
  );
}

/** Footer for lists the server pages (limit/offset): asks for one extra row to know whether a next page exists. */
export function Pager({ page, onPage, hasNext, count }: { page: number; onPage: (p: number) => void; hasNext: boolean; count: number }) {
  if (page === 0 && !hasNext) return null;
  return (
    <div className="flex items-center justify-between border-t border-line px-4 py-2 text-xs text-muted">
      <span>Page {page + 1} · {count} shown</span>
      <PageButtons canPrev={page > 0} canNext={hasNext} onPrev={() => onPage(page - 1)} onNext={() => onPage(page + 1)} />
    </div>
  );
}
