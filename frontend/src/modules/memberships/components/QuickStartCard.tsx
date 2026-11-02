import { useState } from "react";

import { api, Button, Card, Field, FormGrid, Input, NumberInput, toast, unwrap, useCompany, useCurrency, useMutation, useQueryClient, useTranslation } from "@/sdk";

/** For a gym with no plans yet: a name, a price and an optional joining fee make the first plan. The billing item and code are made for it. */
export function QuickStartCard() {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const { company } = useCompany();
  const currency = useCurrency(company?.id);
  const [name, setName] = useState(() => t("quick.defaultName"));
  const [fee, setFee] = useState("");
  const [joining, setJoining] = useState("");
  const make = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/plans", { body: {
      company_id: company?.id ?? "", name: name.trim(), fee, billing_interval: "month", joining_fee: joining || "0", invoice_as_plan_name: true,
      credits_per_period: "0", discount_percent: "0", covered_services: [], rollover: false } })),
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: ["memberships-plans"] });
      void qc.invalidateQueries({ queryKey: ["memberships"] });
      toast(t("planCreated", { name: p.name }), "ok");
    },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const ready = name.trim() !== "" && fee !== "" && Number(fee) >= 0;
  return (
    <Card title={t("quick.title")} description={t("quick.hint")} className="mb-4">
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (ready) make.mutate(); }}>
        <FormGrid>
          <Field label={t("quick.name")} required><Input value={name} maxLength={200} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label={t("quick.fee", { currency: currency ?? "" })} required><NumberInput value={fee} onChange={setFee} /></Field>
          <Field label={t("quick.joining", { currency: currency ?? "" })} hint={t("quick.joiningHint")}><NumberInput value={joining} onChange={setJoining} /></Field>
        </FormGrid>
        <Button type="submit" loading={make.isPending} disabled={!ready}>{t("quick.create")}</Button>
        <p className="text-xs text-muted">{t("quick.note")}</p>
      </form>
    </Card>
  );
}
