import { Plus } from "lucide-react";
import { useEffect, useState } from "react";

import { api, Badge, Button, Card, DataTable, Drawer, Field, FormGrid, Input, Select, Switch, toast, unwrap, useMutation, useQuery, useTranslation, type Schemas } from "@/sdk";

import { useOffers, useRefreshBookings, useResources } from "../hooks";

type Rule = Schemas["CommissionRuleOut"];

/** The rules that say how much a person earns on a sale. Information only: nothing is paid from here. */
export function CommissionRules({ companyId, branchId, currency }: { companyId: string; branchId: string; currency?: string }) {
  const { t } = useTranslation("bookings");
  const [editing, setEditing] = useState<Rule | "new" | null>(null);
  const resources = useResources(branchId, false);
  const offers = useOffers(companyId, false);
  const list = useQuery<Rule[]>({
    queryKey: ["bookings", "commission-rules", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/commission/rules", { params: { query: { company_id: companyId, include_inactive: true } } })),
  });
  const who = (r: Rule) => [
    r.resource_id ? resources.data?.find((p) => p.id === r.resource_id)?.name ?? t("staffPay.rules.aPerson") : null,
    r.level ? t("staffPay.rules.levelOf", { level: r.level }) : null,
    r.offer_id ? offers.data?.find((o) => o.id === r.offer_id)?.name ?? t("staffPay.rules.aService") : null,
  ].filter(Boolean).join(" · ") || t("staffPay.rules.everyone");
  const value = (r: Rule) => (r.kind === "percent" ? `${Number(r.value)}%` : `${r.value}${currency ? ` ${currency}` : ""}`);

  return (
    <Card title={t("staffPay.rules.title")} description={t("staffPay.rules.hint")} actions={<Button size="sm" onClick={() => setEditing("new")}><Plus className="h-4 w-4" />{t("staffPay.rules.add")}</Button>} flush>
      <DataTable
        rows={list.data} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()} rowKey={(r) => r.id}
        empty={{ title: t("staffPay.rules.empty"), hint: t("staffPay.rules.emptyHint"), action: <Button onClick={() => setEditing("new")}>{t("staffPay.rules.add")}</Button> }}
        columns={[
          { header: t("staffPay.rules.appliesTo"), cell: (r) => <button type="button" className="text-left font-medium hover:underline" onClick={() => setEditing(r)}>{t(`staffPay.rules.on.${r.applies_to}`, r.applies_to)}</button> },
          { header: t("staffPay.rules.for"), hideBelow: "sm", cell: who },
          { header: t("staffPay.rules.rate"), align: "right", cell: value },
          { header: t("status.label"), cell: (r) => <Badge tone={r.is_active ? "ok" : "neutral"}>{r.is_active ? t("resources.activeBadge") : t("resources.inactiveBadge")}</Badge> },
        ]}
      />
      <RuleDrawer rule={editing && editing !== "new" ? editing : null} open={editing !== null} onClose={() => setEditing(null)} companyId={companyId} branchId={branchId} who={editing && editing !== "new" ? who(editing) : ""} />
    </Card>
  );
}

function RuleDrawer({ rule, open, onClose, companyId, branchId, who }: { rule: Rule | null; open: boolean; onClose: () => void; companyId: string; branchId: string; who: string }) {
  const { t } = useTranslation("bookings");
  const refresh = useRefreshBookings();
  const resources = useResources(branchId);
  const offers = useOffers(companyId);
  const [applies, setApplies] = useState<"service" | "product">("service");
  const [kind, setKind] = useState<"percent" | "fixed">("percent");
  const [amount, setAmount] = useState("");
  const [person, setPerson] = useState("");
  const [level, setLevel] = useState("");
  const [offer, setOffer] = useState("");
  const [active, setActive] = useState(true);
  useEffect(() => {
    if (!open) return;
    setApplies((rule?.applies_to as "service" | "product") ?? "service"); setKind((rule?.kind as "percent" | "fixed") ?? "percent");
    setAmount(rule ? String(rule.value) : ""); setPerson(rule?.resource_id ?? ""); setLevel(rule?.level ?? ""); setOffer(rule?.offer_id ?? ""); setActive(rule?.is_active ?? true);
  }, [open, rule]);

  const save = useMutation({
    mutationFn: () => (rule
      ? unwrap(api.PATCH("/api/v1/bookings/commission/rules/{rule_id}", { params: { path: { rule_id: rule.id } }, body: { kind, value: amount, is_active: active } }))
      : unwrap(api.POST("/api/v1/bookings/commission/rules", { body: { company_id: companyId, applies_to: applies, kind, value: amount, resource_id: person || null, level: level.trim() || null, offer_id: applies === "service" ? offer || null : null } }))),
    onSuccess: () => { void refresh(); toast(t("staffPay.rules.saved"), "ok"); onClose(); },
  });

  return (
    <Drawer open={open} onClose={onClose} title={rule ? t("staffPay.rules.edit") : t("staffPay.rules.add")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("close")}</Button><Button type="submit" form="rule-form" loading={save.isPending} disabled={amount.trim() === ""}>{t("save")}</Button></>}>
      <form id="rule-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        {rule ? <p className="rounded-xl bg-sunken p-3 text-sm text-muted">{t(`staffPay.rules.on.${rule.applies_to}`)} · {who}. {t("staffPay.rules.editHint")}</p> : (
          <>
            <Field label={t("staffPay.rules.appliesTo")}>
              <Select value={applies} onChange={(e) => setApplies(e.target.value as "service" | "product")}>
                <option value="service">{t("staffPay.rules.on.service")}</option>
                <option value="product">{t("staffPay.rules.on.product")}</option>
              </Select>
            </Field>
            <Field label={t("staffPay.rules.person")} hint={t("staffPay.rules.anyoneHint")}>
              <Select value={person} onChange={(e) => setPerson(e.target.value)}>
                <option value="">{t("staffPay.rules.everyone")}</option>
                {(resources.data ?? []).filter((r) => r.kind === "staff").map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </Select>
            </Field>
            <Field label={t("staffPay.rules.level")} hint={t("staffPay.rules.levelHint")}><Input value={level} maxLength={40} onChange={(e) => setLevel(e.target.value)} /></Field>
            {applies === "service" && (
              <Field label={t("staffPay.rules.service")} hint={t("staffPay.rules.serviceHint")}>
                <Select value={offer} onChange={(e) => setOffer(e.target.value)}>
                  <option value="">{t("staffPay.rules.everyService")}</option>
                  {(offers.data ?? []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                </Select>
              </Field>
            )}
          </>
        )}
        <FormGrid>
          <Field label={t("staffPay.rules.kind")}>
            <Select value={kind} onChange={(e) => setKind(e.target.value as "percent" | "fixed")}>
              <option value="percent">{t("staffPay.rules.percent")}</option>
              <option value="fixed">{t("staffPay.rules.fixed")}</option>
            </Select>
          </Field>
          <Field label={kind === "percent" ? t("staffPay.rules.percentValue") : t("staffPay.rules.fixedValue")} required>
            <Input type="number" inputMode="decimal" min={0} step="any" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </Field>
        </FormGrid>
        {rule && <div className="flex items-center gap-2 text-sm"><Switch checked={active} onChange={setActive} label={t("staffPay.rules.active")} />{t("staffPay.rules.active")}</div>}
      </form>
    </Drawer>
  );
}
