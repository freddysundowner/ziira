import { type FormEvent, useEffect, useState } from "react";

import { api, Button, Drawer, Field, FormGrid, Input, NumberInput, Select, Textarea, toast, today, unwrap, useFormState, useMutation, useTranslation } from "@/sdk";

import { useRefresh, useStaff } from "../hooks";
import type { Project, Rate } from "../types";
import { ClientPicker } from "./ClientPicker";
import { ProjectPicker } from "./ProjectPicker";
import { ServiceItemPicker } from "./ServiceItemPicker";

/** Add a rate to the card (what it covers is fixed once saved), or change the amount, end date or note of one. */
export function RateForm({ open, onClose, companyId, rate, canSeeCost }: { open: boolean; onClose: () => void; companyId: string; rate?: Rate | null; canSeeCost: boolean }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const staff = useStaff(companyId);
  const f = useFormState({ kind: "bill", amount: "", from: today(), to: "", user: "", role: "", note: "" });
  const [project, setProject] = useState<Project | null>(null);
  const [client, setClient] = useState({ id: "", name: "" });
  const [service, setService] = useState("");
  const { reset, set } = f;
  useEffect(() => {
    if (!open) return;
    reset();
    setProject(null); setClient({ id: "", name: "" }); setService("");
    if (rate) { set("kind", rate.kind); set("amount", rate.rate); set("from", rate.effective_from); set("to", rate.effective_to ?? ""); set("note", rate.note ?? ""); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, rate?.id]);

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const v = f.values;
      if (rate) {
        return unwrap(api.PATCH("/api/v1/timebilling/rates/{rate_id}", { params: { path: { rate_id: rate.id } }, body: { rate: v.amount, effective_to: v.to || null, note: v.note.trim() || null } }));
      }
      return unwrap(api.POST("/api/v1/timebilling/rates", { body: {
        company_id: companyId, kind: v.kind as "bill", rate: v.amount, effective_from: v.from, effective_to: v.to || null, project_id: project?.id ?? null,
        client_id: client.id || null, user_id: v.user || null, service_product_id: service || null, role_title: v.role.trim() || null, note: v.note.trim() || null } }));
    },
    onSuccess: () => { void refresh(); toast(t("rates.saved"), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const titles = [...new Set((staff.data ?? []).map((s) => s.title).filter((x): x is string => !!x))];

  return (
    <Drawer open={open} onClose={onClose} title={t(rate ? "rates.edit" : "rates.add")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="rate-form" loading={save.isPending} disabled={!(Number(f.values.amount) >= 0) || f.values.amount === ""}>{t("save")}</Button></>}>
      <form id="rate-form" onSubmit={submit} className="space-y-4">
        {!rate && canSeeCost && (
          <Field label={t("rates.kind")} hint={t(f.values.kind === "bill" ? "rates.kindBillHint" : "rates.kindCostHint")} error={f.error("kind")}>
            <Select {...f.bind("kind")}><option value="bill">{t("rates.kindBill")}</option><option value="cost">{t("rates.kindCost")}</option></Select>
          </Field>
        )}
        <Field label={t("rates.perHour")} required error={f.error("rate")}><NumberInput value={f.values.amount} onChange={(v) => f.set("amount", v)} required /></Field>
        {rate ? (
          <p className="rounded-lg bg-sunken px-3 py-2 text-sm text-muted">{t("rates.fixedCover")}</p>
        ) : (
          <fieldset className="space-y-4 rounded-xl border border-line p-3">
            <legend className="px-1 text-sm font-medium">{t("rates.covers")}</legend>
            <p className="text-xs text-muted">{t("rates.coversHint")}</p>
            <Field label={t("projectField")} error={f.error("project_id")}><ProjectPicker companyId={companyId} activeOnly={false} clearable value={project?.id ?? ""} label={project ? `${project.code} · ${project.name}` : undefined} onChange={setProject} /></Field>
            <Field label={t("client")} error={f.error("client_id")}><ClientPicker clearable value={client.id} label={client.name} onChange={(id, name) => setClient({ id, name })} /></Field>
            <Field label={t("rates.person")} error={f.error("user_id")}>
              <Select {...f.bind("user")}><option value="">{t("rates.anyone")}</option>{(staff.data ?? []).map((s) => <option key={s.user_id} value={s.user_id}>{s.name}</option>)}</Select>
            </Field>
            <Field label={t("projects.serviceItem")} error={f.error("service_product_id")}><ServiceItemPicker value={service} onChange={setService} /></Field>
            <Field label={t("rates.role")} hint={t("rates.roleHint")} error={f.error("role_title")}>
              <Input {...f.bind("role")} maxLength={80} list="rate-titles" />
              <datalist id="rate-titles">{titles.map((x) => <option key={x} value={x} />)}</datalist>
            </Field>
          </fieldset>
        )}
        <FormGrid>
          <Field label={t("rates.from")} required error={f.error("effective_from")}><Input type="date" {...f.bind("from")} required disabled={!!rate} /></Field>
          <Field label={t("rates.to")} hint={t("rates.toHint")} error={f.error("effective_to")}><Input type="date" {...f.bind("to")} min={f.values.from || undefined} /></Field>
        </FormGrid>
        <Field label={t("note")} error={f.error("note")}><Textarea {...f.bind("note")} maxLength={500} /></Field>
      </form>
    </Drawer>
  );
}
