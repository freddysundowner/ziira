import { Plus } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, DataTable, Drawer, Field, FormGrid, Input, NumberInput, PageHeader, Select, Tabs, toast, unwrap, useCan, useCompany, useFormState,
  useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

/** Units of measure, tax codes and price lists: the catalogue's reference data. */
export default function SetupPage() {
  const { t } = useTranslation("products");
  const [tab, setTab] = useState<"uoms" | "taxes" | "lists">("uoms");
  return (
    <>
      <PageHeader title={t("setup")} description={t("setupHint")} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "uoms", label: t("units") }, { id: "taxes", label: t("taxCodes") }, { id: "lists", label: t("priceLists") }]} />
      {tab === "uoms" && <Units />}
      {tab === "taxes" && <Taxes />}
      {tab === "lists" && <Lists />}
    </>
  );
}

function useCreate<T>(key: string, run: () => Promise<T>, done: () => void, f: { fail: (e: unknown) => void }) {
  const qc = useQueryClient();
  const { t } = useTranslation("products");
  return useMutation({
    meta: { silent: true }, mutationFn: run,
    onSuccess: () => { void qc.invalidateQueries({ queryKey: [key] }); toast(t("saved"), "ok"); done(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
}

function Units() {
  const { t } = useTranslation("products");
  const can = useCan("products.manage");
  const [open, setOpen] = useState(false);
  const q = useQuery({ queryKey: ["uoms"], queryFn: () => unwrap(api.GET("/api/v1/products/uoms")) });
  const f = useFormState({ code: "", name: "" });
  const create = useCreate("uoms", () => unwrap(api.POST("/api/v1/products/uoms", { body: { code: f.values.code.trim(), name: f.values.name.trim() } })), () => { f.reset(); setOpen(false); }, f);
  return (
    <>
      <DataTable rows={q.data} loading={q.isLoading} error={q.error?.message} onRetry={() => void q.refetch()} rowKey={(u) => u.id} empty={{ title: t("noUnits"), hint: t("unitsHint") }}
        toolbar={can && <Button className="ml-auto" onClick={() => setOpen(true)}><Plus className="h-4 w-4" />{t("newUnit")}</Button>}
        columns={[{ header: t("code"), cell: (u) => <span className="font-mono text-xs font-medium">{u.code}</span> }, { header: t("name"), cell: (u) => u.name }]} />
      <Drawer open={open} onClose={() => setOpen(false)} title={t("newUnit")} footer={<><Button variant="secondary" onClick={() => setOpen(false)}>{t("cancel")}</Button><Button type="submit" form="uom" loading={create.isPending}>{t("save")}</Button></>}>
        <form id="uom" className="space-y-4" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <Field label={t("code")} hint={t("lettersOnly")} required error={f.error("code")}><Input {...f.bind("code")} required autoFocus maxLength={10} /></Field>
          <Field label={t("name")} required error={f.error("name")}><Input {...f.bind("name")} required /></Field>
        </form>
      </Drawer>
    </>
  );
}

function Taxes() {
  const { t } = useTranslation("products");
  const can = useCan("products.manage");
  const [open, setOpen] = useState(false);
  const q = useQuery({ queryKey: ["tax-codes"], queryFn: () => unwrap(api.GET("/api/v1/products/tax-codes")) });
  const f = useFormState({ code: "", name: "", vat_rate: "", authority_code: "" });
  const create = useCreate("tax-codes", () => unwrap(api.POST("/api/v1/products/tax-codes", { body: { code: f.values.code.trim(), name: f.values.name.trim(), vat_rate: f.values.vat_rate, authority_code: f.values.authority_code.trim() || null } })), () => { f.reset(); setOpen(false); }, f);
  return (
    <>
      <DataTable rows={q.data} loading={q.isLoading} error={q.error?.message} onRetry={() => void q.refetch()} rowKey={(x) => x.id} empty={{ title: t("noTaxCodes"), hint: t("taxHint") }}
        toolbar={can && <Button className="ml-auto" onClick={() => setOpen(true)}><Plus className="h-4 w-4" />{t("newTaxCode")}</Button>}
        columns={[
          { header: t("code"), cell: (x) => <span className="font-mono text-xs font-medium">{x.code}</span> }, { header: t("name"), cell: (x) => x.name },
          { header: t("rate"), align: "right", cell: (x) => `${Number(x.vat_rate)}%` }, { header: t("authorityCode"), hideBelow: "md", cell: (x) => x.authority_code ?? "—" },
        ]} />
      <Drawer open={open} onClose={() => setOpen(false)} title={t("newTaxCode")} footer={<><Button variant="secondary" onClick={() => setOpen(false)}>{t("cancel")}</Button><Button type="submit" form="tax" loading={create.isPending}>{t("save")}</Button></>}>
        <form id="tax" className="space-y-4" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <FormGrid>
            <Field label={t("code")} required error={f.error("code")}><Input {...f.bind("code")} required autoFocus /></Field>
            <Field label={t("rate")} hint={t("rateHint")} required error={f.error("vat_rate")}><NumberInput value={f.values.vat_rate} onChange={(v) => f.set("vat_rate", v)} required /></Field>
          </FormGrid>
          <Field label={t("name")} required error={f.error("name")}><Input {...f.bind("name")} required /></Field>
          <Field label={t("authorityCode")} hint={t("authorityHint")} error={f.error("authority_code")}><Input {...f.bind("authority_code")} /></Field>
        </form>
      </Drawer>
    </>
  );
}

function Lists() {
  const { t } = useTranslation("products");
  const can = useCan("prices.manage");
  const [open, setOpen] = useState(false);
  const { company, companies } = useCompany();
  const q = useQuery({ queryKey: ["price-lists"], queryFn: () => unwrap(api.GET("/api/v1/products/price-lists")) });
  const f = useFormState({ name: "", company_id: "", customer_group: "" });
  const [isDefault, setIsDefault] = useState(false);
  const create = useCreate("price-lists", () => unwrap(api.POST("/api/v1/products/price-lists", { body: { company_id: f.values.company_id || company?.id || "", name: f.values.name.trim(), is_default: isDefault, customer_group: f.values.customer_group.trim() || null } })), () => { f.reset(); setOpen(false); }, f);
  return (
    <>
      <DataTable rows={q.data} loading={q.isLoading} error={q.error?.message} onRetry={() => void q.refetch()} rowKey={(l) => l.id} empty={{ title: t("noPriceLists"), hint: t("listsHint") }}
        toolbar={can && <Button className="ml-auto" onClick={() => setOpen(true)}><Plus className="h-4 w-4" />{t("newPriceList")}</Button>}
        columns={[
          { header: t("name"), cell: (l) => <span className="font-medium">{l.name}</span> }, { header: t("currency"), cell: (l) => l.currency },
          { header: t("customerGroup"), hideBelow: "md", cell: (l) => l.customer_group ?? "—" }, { header: "", cell: (l) => (l.is_default ? <Badge tone="brand">{t("default")}</Badge> : null) },
        ]} />
      <Drawer open={open} onClose={() => setOpen(false)} title={t("newPriceList")} footer={<><Button variant="secondary" onClick={() => setOpen(false)}>{t("cancel")}</Button><Button type="submit" form="plist" loading={create.isPending}>{t("save")}</Button></>}>
        <form id="plist" className="space-y-4" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <Field label={t("name")} required error={f.error("name")}><Input {...f.bind("name")} required autoFocus /></Field>
          {companies.length > 1 && <Field label={t("company")}><Select value={f.values.company_id || company?.id} onChange={(e) => f.set("company_id", e.target.value)}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>}
          <Field label={t("customerGroup")} hint={t("groupHint")}><Input {...f.bind("customer_group")} /></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} className="h-4 w-4 accent-[rgb(var(--brand))]" />{t("makeDefault")}</label>
        </form>
      </Drawer>
    </>
  );
}
