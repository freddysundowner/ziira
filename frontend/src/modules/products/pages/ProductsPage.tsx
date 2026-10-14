import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  api, Badge, Button, Checkbox, DataTable, Drawer, Field, FormGrid, Input, NumberInput, Pager, PageHeader, Select, toast, unwrap, useCan, useCompany,
  useDebounced, useFormState, useMutation, usePagedList, useQuery, useQueryClient, useTranslation, humanise, StatusBadge,
} from "@/sdk";

export default function ProductsPage() {
  const { t } = useTranslation("products");
  const canManage = useCan("products.manage");
  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim());
  const list = usePagedList(["products", q], async (limit, offset) =>
    unwrap(api.GET("/api/v1/products/products", { params: { query: { search: q || undefined, limit, offset } } })));

  return (
    <>
      <PageHeader title={t("title")} description={t("hint")} actions={canManage && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("new")}</Button>} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(p) => p.id}
        rowHref={(p) => `/products/${p.id}`}
        toolbar={<Input className="max-w-sm" aria-label={t("search")} placeholder={t("search")} value={search} onChange={(e) => setSearch(e.target.value)} />}
        empty={{ title: q ? t("noMatch") : t("empty"), hint: q ? undefined : t("emptyHint"), action: canManage && !q ? <Button onClick={() => setCreating(true)}>{t("new")}</Button> : undefined }}
        columns={[
          { header: t("sku"), sortValue: (p) => p.sku, cell: (p) => <span className="font-mono text-xs font-medium">{p.sku}</span> },
          { header: t("name"), sortValue: (p) => p.name, cell: (p) => <span className="font-medium">{p.name}</span> },
          { header: t("type"), hideBelow: "sm", cell: (p) => <Badge>{t(`types.${p.product_type}`, humanise(p.product_type))}</Badge> },
          { header: t("reorderLevel"), hideBelow: "md", align: "right", cell: (p) => p.reorder_level ?? "—" },
          { header: t("status"), hideBelow: "md", cell: (p) => <StatusBadge status={p.is_active ? "active" : "inactive"} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <NewProduct open={creating} onClose={() => setCreating(false)} />
    </>
  );
}

function NewProduct({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation("products");
  const qc = useQueryClient();
  const { company, companies } = useCompany();
  const f = useFormState({ name: "", sku: "", company_id: "", product_type: "stock", base_uom_id: "", tax_code_id: "", reorder_level: "" });
  const [batch, setBatch] = useState(false);
  const [suggestions, setSuggestions] = useState<string[] | null>(null);
  const companyId = f.values.company_id || company?.id || "";
  const uoms = useQuery({ enabled: open, queryKey: ["uoms"], queryFn: () => unwrap(api.GET("/api/v1/products/uoms")) });
  const taxes = useQuery({ enabled: open, queryKey: ["tax-codes"], queryFn: () => unwrap(api.GET("/api/v1/products/tax-codes")) });

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/products/products", { body: {
      company_id: companyId, sku: f.values.sku.trim(), name: f.values.name.trim(), base_uom_id: f.values.base_uom_id || uoms.data?.[0]?.id || "",
      tax_code_id: f.values.tax_code_id || taxes.data?.[0]?.id || "", product_type: f.values.product_type as "stock", is_batch_tracked: batch,
      reorder_level: f.values.reorder_level || null } })),
    onSuccess: (p) => { void qc.invalidateQueries({ queryKey: ["products"] }); toast(t("created", { name: p.name }), "ok"); f.reset(); setBatch(false); setSuggestions(null); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });

  async function suggest() {
    setSuggestions(await unwrap(api.GET("/api/v1/products/sku-suggestions", { params: { query: { company_id: companyId, name: f.values.name } } })).catch(() => []));
  }
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const noSetup = uoms.isSuccess && taxes.isSuccess && (uoms.data.length === 0 || taxes.data.length === 0);

  return (
    <Drawer open={open} onClose={onClose} title={t("new")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="new-product" loading={save.isPending} disabled={noSetup}>{t("save")}</Button></>}>
      <form id="new-product" onSubmit={submit} className="space-y-4">
        {noSetup && <p className="rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn">{t("needSetup")}</p>}
        <Field label={t("name")} required error={f.error("name")}><Input {...f.bind("name")} required autoFocus onChange={(e) => { f.set("name", e.target.value); setSuggestions(null); }} /></Field>
        <Field label={t("sku")} required error={f.error("sku")} hint={t("skuHint")}>
          <div className="flex items-start gap-2">
            <Input {...f.bind("sku")} required />
            <Button variant="secondary" disabled={!f.values.name || !companyId} onClick={() => void suggest()}>{t("suggest")}</Button>
          </div>
        </Field>
        {suggestions && (
          <div className="-mt-2 flex flex-wrap gap-1.5">
            {suggestions.length === 0 && <span className="text-xs text-muted">{t("noSuggestions")}</span>}
            {suggestions.map((s) => <button key={s} type="button" className="rounded-full bg-sunken px-2.5 py-1 font-mono text-xs hover:bg-brand-soft" onClick={() => f.set("sku", s)}>{s}</button>)}
          </div>
        )}
        {companies.length > 1 && (
          <Field label={t("company")}><Select value={companyId} onChange={(e) => f.set("company_id", e.target.value)}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
        )}
        <FormGrid>
          <Field label={t("type")}><Select {...f.bind("product_type")}>{(["stock", "non_stock", "service"] as const).map((v) => <option key={v} value={v}>{t(`types.${v}`)}</option>)}</Select></Field>
          <Field label={t("unit")} error={f.error("base_uom_id")}><Select {...f.bind("base_uom_id")}>{(uoms.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.code} · {u.name}</option>)}</Select></Field>
          <Field label={t("taxCode")} error={f.error("tax_code_id")}><Select {...f.bind("tax_code_id")}>{(taxes.data ?? []).map((x) => <option key={x.id} value={x.id}>{x.code} · {x.name}</option>)}</Select></Field>
          <Field label={t("reorderLevel")} hint={t("reorderHint")} error={f.error("reorder_level")}><NumberInput value={f.values.reorder_level} onChange={(v) => f.set("reorder_level", v)} /></Field>
        </FormGrid>
        <Checkbox label={t("batchTracked")} checked={batch} onChange={(e) => setBatch(e.target.checked)} />
      </form>
    </Drawer>
  );
}
