import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import {
  api,
  Button,
  Card,
  ErrorText,
  errorMessage,
  Field,
  Input,
  PageHeader,
  Select,
  Table,
  useCan,
  useMutation,
  useQuery,
  useCompanies,
  useQueryClient,
  useTranslation,
} from "@/sdk";

export default function ProductsPage() {
  const { t } = useTranslation("products");
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const canManage = useCan("products.manage");
  const products = useQuery({
    queryKey: ["products", search],
    queryFn: async () => (await api.GET("/api/v1/products/products", { params: { query: { search } } })).data ?? [],
  });

  return (
    <>
      <PageHeader title={t("title")} actions={canManage && <Button onClick={() => setCreating(!creating)}>{t("new")}</Button>} />
      {creating && <NewProduct onDone={() => setCreating(false)} />}
      <Card>
        <div className="mb-3 max-w-sm"><Input placeholder={t("search")} value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        <Table
          rows={products.data ?? []}
          rowKey={(p) => p.id}
          empty={t("empty")}
          columns={[
            { header: t("sku"), cell: (p) => <Link className="text-brand hover:underline" to={`/products/${p.id}`}>{p.sku}</Link> },
            { header: t("name"), cell: (p) => p.name },
            { header: t("type"), cell: (p) => t(`types.${p.product_type}`) },
          ]}
        />
      </Card>
    </>
  );
}

function NewProduct({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation("products");
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [sku, setSku] = useState("");
  const [suggestions, setSuggestions] = useState<string[] | null>(null);
  const companies = useCompanies().data ?? [];
  const [chosenCompany, setCompanyId] = useState("");
  const companyId = chosenCompany || companies[0]?.id || "";
  const uoms = useQuery({ queryKey: ["uoms"], queryFn: async () => (await api.GET("/api/v1/products/uoms")).data ?? [] });
  const taxes = useQuery({ queryKey: ["tax-codes"], queryFn: async () => (await api.GET("/api/v1/products/tax-codes")).data ?? [] });

  const save = useMutation({
    mutationFn: async (form: FormData) => {
      const { data, error } = await api.POST("/api/v1/products/products", {
        body: {
          company_id: companyId,
          sku,
          name,
          base_uom_id: String(form.get("uom")),
          tax_code_id: String(form.get("tax")),
          product_type: String(form.get("type")) as "stock" | "non_stock" | "service",
          is_batch_tracked: false,
        },
      });
      if (!data) throw new Error(errorMessage(error));
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["products"] });
      onDone();
    },
  });

  async function suggest() {
    const { data } = await api.GET("/api/v1/products/sku-suggestions", { params: { query: { company_id: companyId, name } } });
    setSuggestions(data ?? []);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    save.mutate(new FormData(event.currentTarget));
  }

  return (
    <Card title={t("new")}>
      <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
        <Field label={t("name")}><Input
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setSuggestions(null); // suggestions were for the old name
            }}
            required
          /></Field>
        <Field label={t("sku")}>
          <div className="flex items-start gap-2">
            <Input value={sku} onChange={(e) => setSku(e.target.value)} required />
            <Button type="button" variant="secondary" className="whitespace-nowrap" disabled={!name || !companyId} onClick={() => void suggest()}>{t("suggest")}</Button>
          </div>
          {suggestions && (
            <div className="flex flex-wrap gap-2 pt-1">
              {suggestions.length === 0 && <span className="text-xs text-slate-500">{t("noSuggestions")}</span>}
              {suggestions.map((s) => (
                <button key={s} type="button" className="rounded bg-slate-100 px-2 py-0.5 text-xs" onClick={() => setSku(s)}>{s}</button>
              ))}
            </div>
          )}
        </Field>
        {companies.length > 1 && (
          <Field label={t("company")}>
            <Select value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
              {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </Select>
          </Field>
        )}
        <Field label={t("type")}>
          <Select name="type" defaultValue="stock">
            {(["stock", "non_stock", "service"] as const).map((v) => <option key={v} value={v}>{t(`types.${v}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("unit")}>
          <Select name="uom" required>{(uoms.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.code} · {u.name}</option>)}</Select>
        </Field>
        <Field label={t("taxCode")}>
          <Select name="tax" required>{(taxes.data ?? []).map((x) => <option key={x.id} value={x.id}>{x.code} · {x.name}</option>)}</Select>
        </Field>
        <div className="md:col-span-2">
          <ErrorText>{save.error?.message}</ErrorText>
          <Button type="submit" disabled={save.isPending}>{t("save")}</Button>
        </div>
      </form>
    </Card>
  );
}
