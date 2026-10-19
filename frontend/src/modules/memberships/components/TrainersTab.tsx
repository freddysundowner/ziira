import { useState } from "react";

import {
  api, Alert, Badge, Button, Card, DataTable, Drawer, Field, FormGrid, Input, money, NumberInput, Select, toast, today, unwrap, useAccess, useCan, useCompany, useCurrency, useMutation,
  useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { daysAgo } from "../gymLogic";

/** Trainer pay: what each trainer earns per session, what they earned in a period, and marking it paid. */
export function TrainersTab() {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const { company } = useCompany();
  const companyId = company?.id ?? "";
  const currency = useCurrency(companyId);
  const hasBookings = useAccess().enabledUnits.has("bookings");
  const canPlans = useCan("memberships.plans");
  const canReports = useCan("memberships.reports");
  const canManage = useCan("memberships.manage");
  const canSee = canReports || canManage || canPlans;
  const [start, setStart] = useState(daysAgo(today(), 30));
  const [end, setEnd] = useState(today());
  const [adding, setAdding] = useState(false);
  const [trainer, setTrainer] = useState("");
  const [service, setService] = useState("");
  const [basis, setBasis] = useState<"fixed" | "percent">("fixed");
  const [amount, setAmount] = useState("");

  const resources = useQuery({
    enabled: hasBookings && adding, queryKey: ["memberships", "trainer-choices"],
    queryFn: () => unwrap(api.GET("/api/v1/bookings/resources", { params: { query: { active_only: true } } })),
  });
  const rates = useQuery({ enabled: !!companyId, queryKey: ["memberships", "trainer-rates", companyId], queryFn: () => unwrap(api.GET("/api/v1/memberships/trainers/rates", { params: { query: { company_id: companyId } } })) });
  const earnings = useQuery({
    enabled: !!companyId && canSee, queryKey: ["memberships", "trainer-earnings", companyId, start, end],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/trainers/earnings", { params: { query: { company_id: companyId, start, end } } })),
  });
  const choice = resources.data?.find((r) => r.id === trainer);
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["memberships", "trainer-rates"] }); void qc.invalidateQueries({ queryKey: ["memberships", "trainer-earnings"] }); };
  const save = useMutation({
    meta: { silent: true }, onError: (e) => toast((e as Error).message, "bad"),
    mutationFn: () => unwrap(api.PUT("/api/v1/memberships/trainers/rates", { body: { company_id: companyId, trainer_ref: trainer, trainer_name: choice?.name ?? "", service_ref: service.trim() || null, basis, amount } })),
    onSuccess: () => { refresh(); setAdding(false); setAmount(""); setService(""); toast(t("trainers.saved"), "ok"); },
  });
  const paid = useMutation({
    meta: { silent: true }, onError: (e) => toast((e as Error).message, "bad"),
    mutationFn: (ref: string) => unwrap(api.POST("/api/v1/memberships/trainers/{trainer_ref}/mark-paid", { params: { path: { trainer_ref: ref }, query: { company_id: companyId } }, body: { through: end } })),
    onSuccess: (r) => { refresh(); toast(t("trainers.markedPaid", { count: r.rows }), "ok"); },
  });

  return (
    <div className="space-y-4">
      <Card title={t("trainers.rates")} description={t("trainers.ratesHint")} actions={canPlans && <Button onClick={() => setAdding(true)}>{t("trainers.setRate")}</Button>}>
        <DataTable rows={rates.data} loading={rates.isLoading} error={rates.error?.message} onRetry={() => void rates.refetch()} rowKey={(r) => r.id} dense
          empty={{ title: t("trainers.noRates"), hint: t("trainers.noRatesHint") }}
          columns={[
            { header: t("extras.trainer"), cell: (r) => <span className="font-medium">{r.trainer_name}</span> },
            { header: t("trainers.service"), hideBelow: "sm", cell: (r) => r.service_ref ?? t("trainers.everyService") },
            { header: t("trainers.rate"), align: "right", cell: (r) => (r.basis === "percent" ? `${Number(r.amount)}%` : money(r.amount, currency)) },
            { header: t("status"), hideBelow: "md", cell: (r) => <Badge tone={r.status === "active" ? "ok" : "neutral"}>{t(`catalogueStatus.${r.status === "active" ? "active" : "retired"}`)}</Badge> },
          ]} />
      </Card>

      {canSee && (
        <Card title={t("trainers.earnings")}>
          <div className="mb-3 flex flex-wrap items-end gap-3">
            <Field label={t("trainers.from")}><Input type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} /></Field>
            <Field label={t("trainers.to")}><Input type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} /></Field>
          </div>
          <DataTable rows={earnings.data} loading={earnings.isLoading} error={earnings.error?.message} onRetry={() => void earnings.refetch()} rowKey={(r) => r.trainer_ref}
            empty={{ title: t("trainers.noEarnings"), hint: t("trainers.noEarningsHint") }}
            columns={[
              { header: t("extras.trainer"), cell: (r) => <span className="font-medium">{r.trainer_name}</span> },
              { header: t("extras.sessions"), align: "right", cell: (r) => r.sessions },
              { header: t("trainers.value"), hideBelow: "sm", align: "right", cell: (r) => money(r.session_value, currency) },
              { header: t("extras.earned"), align: "right", cell: (r) => money(r.earned, currency) },
              { header: t("trainers.paid"), hideBelow: "sm", align: "right", cell: (r) => money(r.paid, currency) },
              { header: "", align: "right", cell: (r) => (canPlans && Number(r.earned) > Number(r.paid) ? <Button size="sm" variant="secondary" loading={paid.isPending} onClick={() => paid.mutate(r.trainer_ref)}>{t("trainers.markPaid", { date: end })}</Button> : null) },
            ]} />
        </Card>
      )}

      <Drawer open={adding} onClose={() => setAdding(false)} title={t("trainers.setRate")}
        footer={<><Button variant="secondary" onClick={() => setAdding(false)}>{t("cancel")}</Button><Button loading={save.isPending} disabled={!trainer || !(Number(amount) >= 0) || amount === ""} onClick={() => save.mutate()}>{t("save")}</Button></>}>
        <div className="space-y-4">
          {!hasBookings && <Alert tone="info">{t("trainers.needBookings")}</Alert>}
          <Field label={t("extras.trainer")} required>
            <Select value={trainer} onChange={(e) => setTrainer(e.target.value)}>
              <option value="">{t("trainers.pick")}</option>
              {resources.data?.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </Select>
          </Field>
          <Field label={t("trainers.service")} hint={t("trainers.serviceHint")}><Input value={service} maxLength={100} onChange={(e) => setService(e.target.value)} /></Field>
          <FormGrid>
            <Field label={t("trainers.basis")}><Select value={basis} onChange={(e) => setBasis(e.target.value as typeof basis)}><option value="fixed">{t("trainers.fixed")}</option><option value="percent">{t("trainers.percent")}</option></Select></Field>
            <Field label={basis === "percent" ? t("trainers.percentOfSession") : t("trainers.amountPerSession")} required><NumberInput value={amount} onChange={setAmount} /></Field>
          </FormGrid>
        </div>
      </Drawer>
    </div>
  );
}
