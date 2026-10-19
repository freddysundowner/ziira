import { type FormEvent, useEffect, useState } from "react";

import {
  api, Alert, Button, Drawer, Field, FormGrid, Input, NumberInput, orNull, Select, Textarea, toast, unwrap, useAccess, useCompany, useFormState,
  useMutation, useQueryClient, useTranslation,
} from "@/sdk";

import { ServicePicker } from "../hooks";
import type { PackageItem } from "../hooks";

const split = (text: string): string[] => text.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);

/** Create or edit a session package that can be sold ("10 massages"). Packages already sold keep what they were sold with. */
export function PackageForm({ open, onClose, item }: { open: boolean; onClose: () => void; item?: PackageItem }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const { company } = useCompany();
  const hasProducts = useAccess().enabledUnits.has("products");
  const editing = !!item;
  const initial = {
    code: item?.code ?? "", name: item?.name ?? "", credits: item?.credits ?? "", price: item?.price ?? "", expiry_days: item?.expiry_days ? String(item.expiry_days) : "",
    covered: (item?.covered_services ?? []).join(", "), terms: item?.terms ?? "", status: item?.status ?? "active", description: item?.description ?? "",
  };
  const f = useFormState(initial);
  const [product, setProduct] = useState(item?.product_id ?? "");
  const { reset } = f;
  useEffect(() => { if (open) { reset(); setProduct(item?.product_id ?? ""); } }, [open, item?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const v = f.values;
      const common = { credits: v.credits || "0", price: v.price || "0", expiry_days: v.expiry_days ? Number(v.expiry_days) : null,
        covered_services: split(v.covered), product_id: product || null, terms: orNull(v.terms), description: orNull(v.description), is_example: false };
      return item
        ? unwrap(api.PATCH("/api/v1/memberships/packages/{package_id}", { params: { path: { package_id: item.id } }, body: { ...common, name: v.name.trim(), status: v.status as "active" } }))
        : unwrap(api.POST("/api/v1/memberships/packages", { body: { ...common, company_id: company?.id ?? "", code: v.code.trim(), name: v.name.trim() } }));
    },
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: ["memberships-packages"] });
      void qc.invalidateQueries({ queryKey: ["memberships"] });
      toast(t(editing ? "packageSaved" : "packageCreated", { name: p.name }), "ok");
      onClose();
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Drawer open={open} onClose={onClose} title={editing ? t("editPackage") : t("newPackage")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="package-form" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="package-form" onSubmit={submit} className="space-y-4">
        <FormGrid>
          <Field label={t("name")} required error={f.error("name")}><Input {...f.bind("name")} required autoFocus maxLength={200} placeholder={t("packageNamePlaceholder")} /></Field>
          <Field label={t("code")} hint={editing ? t("codeFixed") : t("codeHint")} error={f.error("code")}><Input {...f.bind("code")} required disabled={editing} maxLength={30} /></Field>
        </FormGrid>
        <FormGrid>
          <Field label={t("credits")} required error={f.error("credits")}><NumberInput value={f.values.credits} onChange={(v) => f.set("credits", v)} required /></Field>
          <Field label={t("price")} required error={f.error("price")}><NumberInput value={f.values.price} onChange={(v) => f.set("price", v)} required /></Field>
        </FormGrid>
        {item?.is_example && <Alert tone="warn">{t("planx.exampleNote")}</Alert>}
        <Field label={t("planx.description")} hint={t("planx.descriptionHint")} error={f.error("description")}><Textarea rows={2} maxLength={1000} {...f.bind("description")} /></Field>
        <Field label={t("expiryDays")} hint={t("expiryDaysHint")} error={f.error("expiry_days")}>
          <NumberInput value={f.values.expiry_days} onChange={(v) => f.set("expiry_days", v.split(".")[0] ?? "")} />
        </Field>
        <Field label={t("coveredServices")} hint={t("coveredServicesHint")} error={f.error("covered_services")}><Input {...f.bind("covered")} placeholder={t("coveredPlaceholder")} /></Field>
        {hasProducts && <ServicePicker value={product} onChange={setProduct} label={t("invoicedAs")} hint={t("invoicedAsHint")} clearable />}
        <Field label={t("terms")} hint={t("termsHint")} error={f.error("terms")}><Textarea rows={3} maxLength={4000} {...f.bind("terms")} /></Field>
        {editing && (
          <Field label={t("status")} hint={t("retireHint")}>
            <Select {...f.bind("status")}>{(["active", "retired"] as const).map((s) => <option key={s} value={s}>{t(`catalogueStatus.${s}`)}</option>)}</Select>
          </Field>
        )}
      </form>
    </Drawer>
  );
}
