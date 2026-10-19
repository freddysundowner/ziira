import { type FormEvent, useEffect, useState } from "react";

import {
  api, Alert, Button, Drawer, Field, FormGrid, Input, NumberInput, orNull, Select, Switch, Textarea, toast, today, unwrap, useCompany, useCurrency,
  useFormState, useMutation, useQuery, useQueryClient, useTranslation, money,
} from "@/sdk";

import { CustomerPicker, useBranchChoice, useInvoicing } from "../hooks";
import { credits } from "../logic";

/** Sell a session package to a customer. The price starts as the catalogue price and may be changed for this sale. */
export function SellPackageForm({ open, onClose, customerId }: { open: boolean; onClose: () => void; customerId?: string }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const { company } = useCompany();
  const currency = useCurrency(company?.id);
  const f = useFormState({ package_id: "", purchased_on: today(), price: "", notes: "" });
  const [customer, setCustomer] = useState(customerId ?? "");
  const [branch, setBranch] = useState("");
  const [invoiceIt, setInvoiceIt] = useState(true);
  const invoicing = useInvoicing();
  const packages = useQuery({
    queryKey: ["memberships-packages", company?.id, "active"],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/packages", { params: { query: { company_id: company?.id, status: "active", limit: 200 } } })),
  });
  const { branchId, field: branchField } = useBranchChoice(company?.id ?? "", branch, setBranch);
  const item = packages.data?.find((p) => p.id === f.values.package_id);
  const canInvoice = invoicing === true && !!item?.product_id && Number(f.values.price || item?.price || 0) > 0;

  const { reset } = f;
  useEffect(() => { if (open) { reset(); setCustomer(customerId ?? ""); setInvoiceIt(true); } }, [open, customerId]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (id: string) => { f.set("package_id", id); f.set("price", ""); };
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/sold-packages", { body: {
      package_id: f.values.package_id, customer_id: customer, branch_id: branchId, purchased_on: f.values.purchased_on || null,
      price: orNull(f.values.price), notes: orNull(f.values.notes), invoice: canInvoice ? invoiceIt : false } })),
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: ["memberships"] });
      toast(t("packageSold", { name: p.customer_name ?? p.number }), "ok");
      onClose();
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Drawer open={open} onClose={onClose} title={t("sellPackageTitle")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button type="submit" form="sell-package-form" loading={save.isPending} disabled={!customer || !f.values.package_id}>{t("sell")}</Button></>}>
      <form id="sell-package-form" onSubmit={submit} className="space-y-4">
        <CustomerPicker value={customer} onChange={setCustomer} required error={f.error("customer_id")} />
        <Field label={t("package")} required error={f.error("package_id")}>
          <Select value={f.values.package_id} onChange={(e) => pick(e.target.value)} required>
            <option value="">{t("pickPackage")}</option>
            {packages.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </Field>
        {packages.data?.length === 0 && <Alert tone="warn">{t("noPackagesYet")}</Alert>}
        {item && (
          <p className="rounded-md bg-surface-2 p-3 text-sm text-muted">
            {t("packageSummary", { credits: credits(item.credits), price: money(item.price, currency) })}
            {item.expiry_days ? ` ${t("packageExpires", { days: item.expiry_days })}` : ""}
          </p>
        )}
        {branchField}
        <FormGrid>
          <Field label={t("soldOn")} error={f.error("purchased_on")}><Input type="date" {...f.bind("purchased_on")} /></Field>
          <Field label={t("price")} hint={item ? t("priceHint", { price: money(item.price, currency) }) : undefined} error={f.error("price")}>
            <NumberInput value={f.values.price} onChange={(v) => f.set("price", v)} placeholder={item?.price} />
          </Field>
        </FormGrid>
        {item && Number(item.price) > 0 && (canInvoice
          ? <Switch checked={invoiceIt} onChange={setInvoiceIt} label={t("invoiceTheSale")} />
          : <Alert tone="info">{invoicing === false ? t("invoicingOff") : t("packageNeedsService")}</Alert>)}
        <Field label={t("notes")} error={f.error("notes")}><Textarea rows={2} maxLength={1000} {...f.bind("notes")} /></Field>
      </form>
    </Drawer>
  );
}
