import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";

import { Alert, Badge, Button, type Column, DataTable, Drawer, Field, FormGrid, Input, money, NumberInput, type Schemas, Select, Switch, Textarea, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { usePlatformUnits } from "../../catalog";
import { PLAN_CODE } from "../../helpers/plan";
import { useOperatorCan } from "../../me";
import { useChange } from "../../stepUp";
import { useRefreshOperator } from "../billing/invoiceDialogs";
import { PricesPanel } from "./PricesPanel";

type Addon = Schemas["AddonOut"];
type Kind = Schemas["AddonIn"]["kind"];
const KINDS: Kind[] = ["unit", "users", "branches", "companies"];

export default function AddonsTab() {
  const { t } = useTranslation("operator");
  const canEdit = useOperatorCan("platform.plans");
  const [open, setOpen] = useState<string | "new" | null>(null);
  const addons = useQuery({ queryKey: ["operator", "addons"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/addons")) });
  const selected = open && open !== "new" ? addons.data?.find((a) => a.code === open) : undefined;

  const columns: Column<Addon>[] = [
    {
      header: t("plans.addons.addon"), sortValue: (a) => a.sort_order,
      cell: (a) => (
        <button type="button" onClick={() => setOpen(a.code)} className="min-w-0 rounded text-left hover:underline" aria-label={t("plans.addons.open", { name: a.name })}>
          <p className="truncate font-medium">{a.name}</p><p className="truncate font-mono text-xs text-muted">{a.code}</p>
        </button>
      ),
    },
    { header: t("plans.addons.kind"), hideBelow: "sm", cell: (a) => <span className="text-sm">{t(`plans.addons.kinds.${a.kind}`)}{a.kind === "unit" ? ` (${a.unit_name})` : ` +${a.quantity}`}</span> },
    {
      header: t("plans.addons.prices"), hideBelow: "md",
      cell: (a) => {
        const live = (a.current_prices ?? []).filter((p) => !p.withdrawn);
        return <span className="text-xs text-muted">{live.length ? live.map((p) => `${money(p.amount, p.currency)} / ${t(`interval.${p.interval}`)}`).join(" · ") : t("plans.addons.noPrices")}</span>;
      },
    },
    { header: t("plans.visibility"), hideBelow: "sm", cell: (a) => <Badge tone={a.is_public ? "info" : "neutral"}>{t(a.is_public ? "plans.public" : "plans.hidden")}</Badge> },
    { header: t("plans.status"), cell: (a) => <Badge tone={a.status === "active" ? "ok" : "neutral"}>{t(`plans.statuses.${a.status}`, a.status)}</Badge> },
  ];

  return (
    <>
      <DataTable rows={addons.data} columns={columns} rowKey={(a) => a.id} loading={addons.isPending} error={addons.isError ? addons.error.message : null} onRetry={() => void addons.refetch()}
        searchText={(a) => `${a.name} ${a.code}`} searchPlaceholder={t("plans.addons.search")} pageSize={20}
        empty={{ title: t("plans.addons.empty"), hint: canEdit ? t("plans.addons.emptyHint") : undefined }}
        toolbar={canEdit ? <Button className="ml-auto" size="sm" onClick={() => setOpen("new")}><Plus className="h-4 w-4" /> {t("plans.addons.new")}</Button> : undefined} />
      {open === "new" && <AddonDrawer onClose={() => setOpen(null)} onCreated={(code) => setOpen(code)} />}
      {selected && <AddonDrawer addon={selected} onClose={() => setOpen(null)} />}
    </>
  );
}

function AddonDrawer({ addon, onClose, onCreated }: { addon?: Addon; onClose: () => void; onCreated?: (code: string) => void }) {
  const { t } = useTranslation("operator");
  const canEdit = useOperatorCan("platform.plans");
  const refresh = useRefreshOperator();
  const units = usePlatformUnits();
  const creating = !addon;
  const [f, setF] = useState({
    code: addon?.code ?? "", name: addon?.name ?? "", description: addon?.description ?? "", kind: (addon?.kind ?? "users") as Kind, unit_name: addon?.unit_name ?? "",
    quantity: String(addon?.quantity ?? 1), is_public: addon?.is_public ?? false, sort_order: String(addon?.sort_order ?? 100), status: (addon?.status ?? "active") as "active" | "retired",
  });
  const [showErrors, setShowErrors] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const patch = (p: Partial<typeof f>) => { setF((v) => ({ ...v, ...p })); setProblem(null); };

  const quantity = Number(f.quantity), order = Number(f.sort_order);
  const errors: Record<string, string> = {};
  if (creating && !PLAN_CODE.test(f.code.trim())) errors.code = "code";
  if (!f.name.trim()) errors.name = "nameRequired";
  if (creating && f.kind === "unit" && !f.unit_name) errors.unit_name = "unit";
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > 100000) errors.quantity = "quantity";
  if (!Number.isInteger(order) || order < 0 || order > 100000) errors.sort_order = "sortOrder";
  const err = (key: string) => (showErrors && errors[key] ? t(`plans.addons.errors.${errors[key]}`) : null);

  const save = useChange(
    () => creating
      ? opUnwrap(opApi.POST("/api/v1/operator/addons", { body: { code: f.code.trim(), name: f.name.trim(), description: f.description.trim(), kind: f.kind, unit_name: f.kind === "unit" ? f.unit_name : null, quantity, is_public: f.is_public, sort_order: order } }))
      : opUnwrap(opApi.PATCH("/api/v1/operator/addons/{code}", { params: { path: { code: addon.code } }, body: { name: f.name.trim(), description: f.description.trim(), quantity, is_public: f.is_public, sort_order: order, status: f.status } })),
    {
      onSuccess: (saved) => { toast(t(creating ? "plans.addons.created" : "plans.addons.saved", { name: saved.name }), "ok"); refresh(); if (creating) onCreated?.(saved.code); else onClose(); },
      onError: (error) => setProblem(error.message),
    },
  );
  const submit = () => {
    if (!canEdit || save.isPending) return;
    if (Object.keys(errors).length > 0) { setShowErrors(true); return; }
    save.mutate(undefined);
  };

  return (
    <Drawer open onClose={onClose} title={creating ? t("plans.addons.new") : addon.name}
      footer={canEdit ? <><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="addon-form" loading={save.isPending}>{t(creating ? "plans.addons.create" : "plans.editor.save")}</Button></> : undefined}>
      <div className="space-y-5">
        <form id="addon-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <fieldset disabled={!canEdit} className="space-y-4">
            <FormGrid>
              <Field label={t("plans.editor.code")} hint={creating ? t("plans.editor.codeHint") : t("plans.editor.codeFixed")} error={err("code")} required={creating}>
                <Input value={f.code} onChange={(e) => patch({ code: e.target.value })} readOnly={!creating} maxLength={40} className="font-mono" autoComplete="off" />
              </Field>
              <Field label={t("plans.editor.name")} error={err("name")} required><Input value={f.name} onChange={(e) => patch({ name: e.target.value })} maxLength={80} /></Field>
            </FormGrid>
            <Field label={t("plans.editor.description")}><Textarea value={f.description} onChange={(e) => patch({ description: e.target.value })} rows={2} maxLength={500} /></Field>
            <FormGrid>
              <Field label={t("plans.addons.kind")} hint={creating ? t("plans.addons.kindHint") : t("plans.addons.kindFixed")}>
                <Select value={f.kind} disabled={!creating} onChange={(e) => patch({ kind: e.target.value as Kind })}>{KINDS.map((k) => <option key={k} value={k}>{t(`plans.addons.kinds.${k}`)}</option>)}</Select>
              </Field>
              {f.kind === "unit" && (
                <Field label={t("plans.addons.unit")} error={err("unit_name")}>
                  <Select value={f.unit_name} disabled={!creating} onChange={(e) => patch({ unit_name: e.target.value })}>
                    <option value="">{t("plans.addons.chooseUnit")}</option>
                    {(units.data ?? []).filter((u) => u.kind !== "kernel").map((u) => <option key={u.name} value={u.name}>{u.title}</option>)}
                    {f.unit_name && !(units.data ?? []).some((u) => u.name === f.unit_name) && <option value={f.unit_name}>{f.unit_name}</option>}
                  </Select>
                </Field>
              )}
              <Field label={t("plans.addons.quantity")} hint={f.kind === "unit" ? t("plans.addons.quantityUnitHint") : t("plans.addons.quantityHint")} error={err("quantity")}><NumberInput value={f.quantity} onChange={(v) => patch({ quantity: v })} /></Field>
              <Field label={t("plans.editor.sortOrder")} error={err("sort_order")}><NumberInput value={f.sort_order} onChange={(v) => patch({ sort_order: v })} /></Field>
            </FormGrid>
            <div className="flex items-start gap-3"><Switch checked={f.is_public} onChange={(v) => patch({ is_public: v })} label={t("plans.editor.public")} /><div><p className="text-sm font-medium">{t("plans.editor.public")}</p><p className="text-xs text-muted">{t("plans.addons.publicHint")}</p></div></div>
            {!creating && (
              <Field label={t("plans.editor.state")}>
                <Select value={f.status} onChange={(e) => patch({ status: e.target.value as "active" | "retired" })}>
                  <option value="active">{t("plans.statuses.active")}</option><option value="retired">{t("plans.statuses.retired")}</option>
                </Select>
              </Field>
            )}
          </fieldset>
          {problem && <Alert tone="bad">{problem}</Alert>}
        </form>

        {addon ? (
          <section>
            <h3 className="mb-2 text-sm font-semibold">{t("plans.price.title")}</h3>
            <PricesPanel prices={addon.prices ?? []} current={addon.current_prices ?? []} intervals={["month", "year", "one_time"]} canEdit={canEdit}
              add={(body) => opUnwrap(opApi.POST("/api/v1/operator/addons/{code}/prices", { params: { path: { code: addon.code } }, body }))}
              remove={(id) => opUnwrap(opApi.DELETE("/api/v1/operator/addons/{code}/prices/{price_id}", { params: { path: { code: addon.code, price_id: id } } }))} />
          </section>
        ) : <Alert tone="info">{t("plans.editor.pricesAfter")}</Alert>}
      </div>
    </Drawer>
  );
}
