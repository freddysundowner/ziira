import { Plus } from "lucide-react";
import { useState } from "react";

import { Alert, api, Button, Card, ConfirmDialog, PageHeader, Tabs, toast, today, unwrap, useMutation, useQuery, useTranslation } from "@/sdk";

import { CompanyPicker } from "../components/CompanyBar";
import { RateChecker } from "../components/RateChecker";
import { RateForm } from "../components/RateForm";
import { RateTable } from "../components/RateTable";
import { StaffTab } from "../components/StaffTab";
import { useRefresh, useWorkCompany } from "../hooks";
import type { Rate } from "../types";

/** Rate cards: what each hour is billed at (and what it costs), by project, client, person, service or role; and staff titles. */
export default function RatesPage() {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const { companyId, companies, setCompanyId, currency } = useWorkCompany();
  const [tab, setTab] = useState<"rates" | "staff">("rates");
  const [form, setForm] = useState<{ rate: Rate | null } | null>(null);
  const [removing, setRemoving] = useState<Rate | null>(null);
  const rates = useQuery({
    queryKey: ["timebilling", "rates", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/rates", { params: { query: { company_id: companyId } } })),
  });
  const clients = useQuery({
    queryKey: ["timebilling", "clients", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/clients", { params: { query: { company_id: companyId } } })),
  });
  const end = useMutation({
    mutationFn: (r: Rate) => unwrap(api.PATCH("/api/v1/timebilling/rates/{rate_id}", { params: { path: { rate_id: r.id } }, body: { effective_to: today() } })),
    onSuccess: () => void refresh(),
  });
  const confirm = useMutation({
    mutationFn: (r: Rate) => unwrap(api.PATCH("/api/v1/timebilling/rates/{rate_id}", { params: { path: { rate_id: r.id } }, body: { example: false } })),
    onSuccess: () => { toast(t("rates.confirmed"), "ok"); void refresh(); },
  });
  const remove = useMutation({
    mutationFn: (r: Rate) => unwrap(api.DELETE("/api/v1/timebilling/rates/{rate_id}", { params: { path: { rate_id: r.id } } })),
    onSuccess: () => { setRemoving(null); void refresh(); },
  });
  const bill = rates.data?.filter((r) => r.kind === "bill");
  const cost = rates.data?.filter((r) => r.kind === "cost");
  const table = (rows: Rate[] | undefined, empty: { title: string; hint?: string }) => (
    <RateTable rates={rows} loading={rates.isLoading} error={rates.error?.message} onRetry={() => void rates.refetch()} companyId={companyId} clients={clients.data} currency={currency}
      onEdit={(rate) => setForm({ rate })} onConfirm={(r) => confirm.mutate(r)} onEnd={(r) => end.mutate(r)} onDelete={setRemoving} empty={empty} />
  );

  return (
    <>
      <PageHeader title={t("rates.title")} description={t("rates.hint")}
        actions={<><CompanyPicker companies={companies} value={companyId} onChange={setCompanyId} />{tab === "rates" && <Button onClick={() => setForm({ rate: null })}><Plus className="h-4 w-4" />{t("rates.add")}</Button>}</>} />
      <Tabs tabs={[{ id: "rates", label: t("rates.tabRates") }, { id: "staff", label: t("rates.tabStaff") }]} value={tab} onChange={setTab} />
      {tab === "staff" ? <StaffTab companyId={companyId} /> : (
        <div className="space-y-6">
          {rates.data?.some((r) => r.example) && <Alert tone="warn">{t("rates.exampleNote")}</Alert>}
          <Card title={t("rates.howTitle")}>
            <p className="text-sm text-muted">{t("rates.how")}</p>
            <ol className="mt-2 list-decimal space-y-0.5 pl-5 text-sm">{(["project", "client", "person", "service", "role"] as const).map((k) => <li key={k}>{t(`rates.order.${k}`)}</li>)}</ol>
            <p className="mt-2 text-sm text-muted">{t("rates.howTie")}</p>
          </Card>
          <section>
            <h2 className="mb-2 text-sm font-semibold">{t("rates.billTitle")}</h2>
            {table(bill, { title: t("rates.billEmpty"), hint: t("rates.billEmptyHint") })}
          </section>
          <section>
            <h2 className="mb-2 text-sm font-semibold">{t("rates.costTitle")}</h2>
            <p className="mb-2 text-xs text-muted">{t("rates.costHint")}</p>
            {table(cost, { title: t("rates.costEmpty") })}
          </section>
          <RateChecker companyId={companyId} currency={currency} canSeeCost />
        </div>
      )}
      <RateForm open={!!form} onClose={() => setForm(null)} companyId={companyId} rate={form?.rate} canSeeCost />
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} onConfirm={() => removing && remove.mutate(removing)} busy={remove.isPending} danger
        title={t("delete")} message={t("rates.deleteAsk")} confirmLabel={t("delete")} />
    </>
  );
}
