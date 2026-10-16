import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { Alert, Badge, Card, EmptyState, ErrorState, Skeleton, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { KEYS } from "./api";

type Plan = { code?: string; name?: string; description?: string; highlights?: string[]; prices?: { currency: string; interval: string; amount: string; tax_inclusive?: boolean }[]; contact_only?: boolean };

/** The public plans exactly as the website receives them (read only: plans and prices are edited under Plans). */
export default function PricingTab() {
  const { t } = useTranslation("operator");
  const plans = useQuery({ queryKey: KEYS.plans, queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/site/plans")) });
  if (plans.isPending) return <div className="space-y-3"><Skeleton className="h-24 w-full" /><Skeleton className="h-24 w-full" /></div>;
  if (plans.isError) return <ErrorState message={plans.error.message} onRetry={() => void plans.refetch()} />;
  const list = plans.data.plans as Plan[];
  return (
    <>
      <Alert tone="info" className="mb-4">
        {t("website.pricing.note")} <Link to="/operator/plans" className="font-medium underline">{t("website.pricing.edit")}</Link>
      </Alert>
      {list.length === 0 ? <EmptyState title={t("website.pricing.empty")} hint={t("website.pricing.emptyHint")} /> : (
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {list.map((p) => (
            <Card key={p.code ?? p.name} title={p.name} description={p.description}>
              {p.contact_only ? <Badge tone="info">{t("website.pricing.contactOnly")}</Badge> : (
                <ul className="space-y-1 text-sm">
                  {(p.prices ?? []).map((x) => <li key={`${x.currency}${x.interval}`} className="tnum flex justify-between"><span>{x.currency} / {x.interval}</span><span className="font-medium">{x.amount}</span></li>)}
                  {(p.prices ?? []).length === 0 && <li className="text-muted">{t("website.pricing.noPrice")}</li>}
                </ul>
              )}
              {(p.highlights ?? []).length > 0 && <ul className="mt-3 list-disc space-y-0.5 pl-4 text-xs text-muted">{(p.highlights ?? []).map((h) => <li key={h}>{h}</li>)}</ul>}
            </Card>
          ))}
        </div>
      )}
      <p className="mt-4 text-xs text-muted">{t("website.pricing.rebuild")}</p>
    </>
  );
}
