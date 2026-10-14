import { useState } from "react";

import {
  api, Button, Card, DataTable, Field, FormGrid, formatDate, money, NumberInput, Select, Input, today, toast, unwrap, useCan, useCurrency, useFormState,
  useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

/** A product's prices on each price list: current and past, with a form to set a new price from a date. */
export function PricesTab({ productId }: { productId: string }) {
  const { t } = useTranslation("products");
  const qc = useQueryClient();
  const canPrice = useCan("prices.manage");
  const currency = useCurrency();
  const lists = useQuery({ queryKey: ["price-lists"], queryFn: () => unwrap(api.GET("/api/v1/products/price-lists")) });
  const [chosen, setChosen] = useState("");
  const listId = chosen || lists.data?.[0]?.id || "";
  const prices = useQuery({
    enabled: !!listId, queryKey: ["prices", listId, productId],
    queryFn: () => unwrap(api.GET("/api/v1/products/price-lists/{price_list_id}/prices", { params: { path: { price_list_id: listId }, query: { product_id: productId } } })),
  });
  const f = useFormState({ price: "", valid_from: today() });
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.PUT("/api/v1/products/price-lists/{price_list_id}/prices", { params: { path: { price_list_id: listId } }, body: { product_id: productId, price: f.values.price, valid_from: f.values.valid_from } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["prices", listId, productId] }); toast(t("priceSaved"), "ok"); f.set("price", ""); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });

  if (lists.isSuccess && lists.data.length === 0) return <Card><p className="text-sm text-muted">{t("noPriceLists")}</p></Card>;
  const listCurrency = lists.data?.find((l) => l.id === listId)?.currency ?? currency;
  return (
    <div className="space-y-4">
      <Card title={t("priceList")} actions={
        <Select aria-label={t("priceList")} value={listId} onChange={(e) => setChosen(e.target.value)} className="w-56">
          {(lists.data ?? []).map((l) => <option key={l.id} value={l.id}>{l.name}{l.is_default ? ` · ${t("default")}` : ""}</option>)}
        </Select>}>
        <p className="mb-3 text-xs text-muted">{t("pricesInclude")}</p>
        <DataTable rows={prices.data} loading={prices.isLoading} error={prices.error?.message} onRetry={() => void prices.refetch()} rowKey={(p) => p.id}
          empty={{ title: t("noPrices") }}
          columns={[
            { header: t("price"), align: "right", cell: (p) => <span className="font-medium">{money(p.price, listCurrency)}</span> },
            { header: t("from"), cell: (p) => formatDate(p.valid_from) },
            { header: t("until"), cell: (p) => (p.valid_to ? formatDate(p.valid_to) : <span className="text-ok">{t("current")}</span>) },
          ]} />
      </Card>
      {canPrice && (
        <Card title={t("setPrice")}>
          <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
            <FormGrid>
              <Field label={t("price")} required error={f.error("price")}><NumberInput value={f.values.price} onChange={(v) => f.set("price", v)} required /></Field>
              <Field label={t("from")} required error={f.error("valid_from")}><Input type="date" {...f.bind("valid_from")} required /></Field>
            </FormGrid>
            <Button type="submit" loading={save.isPending} disabled={!f.values.price}>{t("savePrice")}</Button>
          </form>
        </Card>
      )}
    </div>
  );
}
