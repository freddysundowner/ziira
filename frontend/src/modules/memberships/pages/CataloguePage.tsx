import { CalendarClock, Plus } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  api, Badge, Button, DataTable, formatDate, money, PageHeader, Tabs, unwrap, useCan, useCompany, useCurrency, useQuery, useTranslation,
} from "@/sdk";

import { PackageForm } from "../components/CatalogueForms";
import { PlanForm } from "../components/PlanForm";
import { PriceChangesDrawer } from "../components/PriceChangesDrawer";
import { TermsEditor } from "../components/TermsEditor";
import { PoliciesCard } from "../components/PoliciesCard";
import { usePlans } from "../hooks";
import type { PackageItem, Plan } from "../hooks";
import { credits } from "../logic";

type Tab = "plans" | "packages" | "policies" | "terms";

/** What the business sells: membership plans and session packages, and the policies that apply to them. */
export default function CataloguePage() {
  const { t } = useTranslation("memberships");
  const canEdit = useCan("memberships.plans");
  const { company } = useCompany();
  const currency = useCurrency(company?.id);
  const [params] = useSearchParams();
  const asked = params.get("tab");
  const [tab, setTab] = useState<Tab>(asked === "policies" || asked === "terms" || asked === "packages" ? asked : "plans");
  const [plan, setPlan] = useState<Plan | "new" | null>(null);
  const [pricing, setPricing] = useState<Plan | null>(null);
  const [item, setItem] = useState<PackageItem | "new" | null>(null);
  const plans = usePlans(company?.id);
  const packages = useQuery({
    enabled: !!company, queryKey: ["memberships-packages", company?.id],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/packages", { params: { query: { company_id: company?.id, limit: 200 } } })),
  });
  const tone = (status: string) => (status === "active" ? "ok" : "neutral") as "ok" | "neutral";

  return (
    <>
      <PageHeader title={t("catalogueMenu")} description={t("catalogueHint")}
        actions={canEdit && (tab === "plans" || tab === "packages") && (
          <Button onClick={() => (tab === "plans" ? setPlan("new") : setItem("new"))}><Plus className="h-4 w-4" />{tab === "plans" ? t("newPlan") : t("newPackage")}</Button>)} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "plans", label: t("tabs.plans"), count: plans.data?.length }, { id: "packages", label: t("tabs.catalogue"), count: packages.data?.length }, { id: "policies", label: t("tabs.policies") }, { id: "terms", label: t("tabs.terms") }]} />
      {tab === "plans" && (
        <DataTable rows={plans.data} loading={plans.isLoading} error={plans.error?.message} onRetry={() => void plans.refetch()} rowKey={(p) => p.id}
          empty={{ title: t("noPlans"), hint: t("noPlansHint"), action: canEdit ? <Button onClick={() => setPlan("new")}>{t("newPlan")}</Button> : undefined }}
          columns={[
            { header: t("plan"), sortValue: (p) => p.name, cell: (p) => (
              <button type="button" className="text-left" onClick={() => setPlan(p)}>
                <span className="font-medium text-brand-strong hover:underline">{p.name}</span><span className="block font-mono text-xs text-muted">{p.code}</span>
              </button>) },
            { header: t("planx.kind"), hideBelow: "sm", cell: (p) => (
              <span className="flex flex-wrap gap-1"><Badge tone="neutral">{t(`planx.kinds.${p.kind}`, p.kind)}</Badge>{p.is_trial && <Badge tone="info">{t("badge.trial")}</Badge>}{p.is_example && <Badge tone="warn">{t("planx.exampleBadge")}</Badge>}</span>) },
            { header: t("fee"), align: "right", cell: (p) => (
              <span>{p.kind === "pass" ? money(p.current_fee, currency) : `${money(p.current_fee, currency)} / ${t(`intervalShort.${p.billing_interval}`)}`}
                {p.next_fee !== null && p.next_fee_from && <span className="block text-xs text-muted">{t("priceChange.next", { fee: money(p.next_fee, currency), date: formatDate(p.next_fee_from) })}</span>}</span>) },
            { header: t("creditsPerPeriod"), hideBelow: "sm", align: "right", cell: (p) => credits(p.credits_per_period) },
            { header: t("discountPercent"), hideBelow: "md", align: "right", cell: (p) => `${credits(p.discount_percent)}%` },
            { header: t("status"), cell: (p) => <Badge tone={tone(p.status)}>{t(`catalogueStatus.${p.status}`, p.status)}</Badge> },
            { header: "", align: "right", cell: (p) => <Button size="sm" variant="secondary" onClick={() => setPricing(p)}><CalendarClock className="h-3.5 w-3.5" />{t("priceChange.button")}</Button> },
          ]} />
      )}
      {tab === "packages" && (
        <DataTable rows={packages.data} loading={packages.isLoading} error={packages.error?.message} onRetry={() => void packages.refetch()} rowKey={(p) => p.id}
          empty={{ title: t("noPackages"), hint: t("noPackagesHint"), action: canEdit ? <Button onClick={() => setItem("new")}>{t("newPackage")}</Button> : undefined }}
          columns={[
            { header: t("package"), sortValue: (p) => p.name, cell: (p) => (
              <button type="button" className="text-left" onClick={() => setItem(p)}>
                <span className="font-medium text-brand-strong hover:underline">{p.name}</span><span className="block font-mono text-xs text-muted">{p.code}</span>
              </button>) },
            { header: t("credits"), align: "right", cell: (p) => credits(p.credits) },
            { header: t("price"), align: "right", cell: (p) => <span>{money(p.price, currency)}{p.is_example && <Badge tone="warn" className="ml-2">{t("planx.exampleBadge")}</Badge>}</span> },
            { header: t("expiry"), hideBelow: "sm", cell: (p) => (p.expiry_days ? t("expiryDaysValue", { count: p.expiry_days }) : t("neverExpires")) },
            { header: t("status"), cell: (p) => <Badge tone={tone(p.status)}>{t(`catalogueStatus.${p.status}`, p.status)}</Badge> },
          ]} />
      )}
      {tab === "policies" && <PoliciesCard />}
      {tab === "terms" && <TermsEditor />}
      <PriceChangesDrawer plan={pricing} onClose={() => setPricing(null)} />
      <PlanForm open={plan !== null} onClose={() => setPlan(null)} plan={plan === "new" || plan === null ? undefined : plan} />
      <PackageForm open={item !== null} onClose={() => setItem(null)} item={item === "new" || item === null ? undefined : item} />
    </>
  );
}
