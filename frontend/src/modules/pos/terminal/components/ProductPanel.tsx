import { Search } from "lucide-react";
import { type FormEvent, type KeyboardEvent, type RefObject, useEffect, useState } from "react";

import { api, Badge, cx, ErrorState, money, quantity, Skeleton, toast, unwrap, useDebounced, useQuery, useQueryClient, useTranslation } from "@/sdk";

import type { CatalogItem } from "../cart";

const PAGE = 60;

/** Search by name or SKU and a grid to tap. A barcode scanner types the code and presses Enter, which adds the product. */
export function ProductPanel({ branchId, locationId, currency, searchRef, onAdd, canSetPrice }: {
  branchId: string; locationId: string | undefined; currency: string; searchRef: RefObject<HTMLInputElement>;
  onAdd: (item: CatalogItem) => void; canSetPrice: boolean;
}) {
  const { t } = useTranslation("pos");
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [active, setActive] = useState(-1);
  const q = useDebounced(text.trim(), 150);

  const lookup = (search: string) => ({
    queryKey: ["pos-terminal", "catalog", branchId, locationId, search],
    queryFn: () => unwrap(api.GET("/api/v1/pos/catalog", { params: { query: { branch_id: branchId, location_id: locationId, search: search || undefined, limit: PAGE } } })),
    staleTime: 30_000,
  });
  const items = useQuery({ ...lookup(q), placeholderData: (previous) => previous });
  const shown = items.data ?? [];
  useEffect(() => setActive(-1), [q]);

  const add = (item: CatalogItem) => {
    if (item.price === null && !canSetPrice) { toast(t("terminal.products.noPrice", { name: item.name }), "warn"); return; }
    onAdd(item);
    setText("");
    setActive(-1);
    searchRef.current?.focus();
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    const code = text.trim();
    if (!code) return;
    if (active >= 0 && shown[active]) { add(shown[active]!); return; }
    try {
      const found = await qc.fetchQuery(lookup(code));
      const exact = found.filter((i) => i.sku.toLowerCase() === code.toLowerCase());
      const pick = exact.length === 1 ? exact[0] : found.length === 1 ? found[0] : undefined;
      if (pick) add(pick);
      else if (found.length === 0) { toast(t("terminal.products.notFound", { code }), "warn"); searchRef.current?.select(); }
      else toast(t("terminal.products.several"), "info");
    } catch (error) {
      toast((error as Error).message, "bad");
    }
  }

  function keys(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, shown.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, -1)); }
    else if (e.key === "Escape") { setText(""); setActive(-1); }
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col" aria-label={t("terminal.products.title")}>
      <form onSubmit={(e) => void submit(e)} className="shrink-0 border-b border-line bg-surface p-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-3.5 h-5 w-5 text-muted" />
          <input ref={searchRef} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={keys} autoFocus autoComplete="off" spellCheck={false}
            aria-label={t("terminal.products.search")} placeholder={t("terminal.products.search")}
            className="h-12 w-full rounded-xl border border-line bg-bg pl-11 pr-3 text-base focus:border-brand" />
        </div>
        <p className="mt-1.5 hidden text-xs text-muted sm:block">{t("terminal.products.scanHint")}</p>
      </form>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {items.isLoading ? (
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-24" />)}</div>
        ) : items.error && !items.data ? (
          <ErrorState title={t("terminal.products.failed")} message={items.error.message} onRetry={() => void items.refetch()} />
        ) : shown.length === 0 ? (
          <p className="py-16 text-center text-sm text-muted">{q ? t("terminal.products.noMatch", { q }) : t("terminal.products.empty")}</p>
        ) : (
          <>
            {items.error && <p role="alert" className="mb-2 rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">{items.error.message}</p>}
            <ul className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-4">
              {shown.map((item, i) => {
                const out = item.stock !== null && item.stock !== undefined && Number(item.stock) <= 0;
                return (
                  <li key={item.product_id}>
                    <button type="button" onClick={() => add(item)}
                      className={cx("flex min-h-[6rem] w-full flex-col justify-between rounded-xl border bg-surface p-3 text-left shadow-card transition-colors hover:border-brand active:bg-brand-soft",
                        i === active ? "border-brand ring-2 ring-brand" : "border-line")}>
                      <span className="line-clamp-2 text-sm font-medium leading-snug">{item.name}</span>
                      <span className="mt-2 flex items-end justify-between gap-2">
                        <span className="tnum text-sm font-semibold text-brand-strong">{item.price === null ? t("terminal.products.setPrice") : money(item.price, currency)}</span>
                        {item.stock !== null && item.stock !== undefined && <Badge tone={out ? "bad" : "neutral"}>{out ? t("terminal.products.out") : quantity(item.stock)}</Badge>}
                      </span>
                      <span className="mt-1 truncate font-mono text-[11px] text-muted">{item.sku}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
            {shown.length >= PAGE && <p className="mt-3 text-center text-xs text-muted">{t("terminal.products.refine")}</p>}
          </>
        )}
      </div>
    </section>
  );
}
