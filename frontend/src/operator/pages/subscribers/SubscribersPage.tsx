import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Badge, Button, type Column, DataTable, formatDate, Input, money, PageHeader, Pager, type Schemas, Select, useDebounced, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { SubscriptionBadge } from "../../components/bits";
import { useEditions, usePlans } from "../../catalog";
import { moneyMap, SUBSCRIPTION_STATUSES } from "../../helpers/format";
import { filtersFromParams, filtersToParams, FLAGS, hasFilters, NO_FILTERS, subscriberQuery, type SubscriberFilters } from "../../helpers/subscribers";

type Row = Schemas["SubscriberRow"];
const PAGE_SIZE = 25;

export default function SubscribersPage() {
  const { t } = useTranslation("operator");
  const [params, setParams] = useSearchParams();
  const filters = filtersFromParams(params);
  const [page, setPage] = useState(0);
  const [typed, setTyped] = useState(filters.search);
  const search = useDebounced(typed.trim());
  const effective = { ...filters, search };
  const plans = usePlans();
  const editions = useEditions();

  const change = (patch: Partial<SubscriberFilters>) => {
    setPage(0);
    setParams(filtersToParams({ ...filters, search: typed, ...patch }), { replace: true });
  };
  const list = useQuery({
    queryKey: ["operator", "subscribers", effective, page],
    queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/subscribers", { params: { query: subscriberQuery(effective, page, PAGE_SIZE) } })),
    placeholderData: keepPreviousData,
  });

  const columns: Column<Row>[] = [
    {
      header: t("subs.subscriber"),
      cell: (s) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{s.name}</p>
          <p className="truncate font-mono text-xs text-muted">{s.code}{s.country ? ` · ${s.country}` : ""}</p>
        </div>
      ),
    },
    {
      header: t("subs.status"),
      cell: (s) => (
        <div className="flex flex-wrap gap-1">
          <SubscriptionBadge status={s.status} />
          {s.is_comp && <Badge tone="brand">{t("subs.comp")}</Badge>}
          {s.cancel_at_period_end && <Badge tone="warn">{t("subs.cancelling")}</Badge>}
          {s.tenant_status !== "active" && <Badge tone="bad">{t("subs.businessState", { state: s.tenant_status })}</Badge>}
        </div>
      ),
    },
    {
      header: t("subs.plan"), hideBelow: "md",
      cell: (s) => s.plan_name ? (
        <div>
          <p className="text-sm">{s.plan_name}</p>
          <p className="text-xs text-muted">{s.unit_amount !== null && s.currency ? `${money(s.unit_amount, s.currency)}${s.interval ? ` / ${t(`interval.${s.interval}`)}` : ""}` : "-"}</p>
        </div>
      ) : <span className="text-sm text-muted">-</span>,
    },
    {
      header: t("subs.until"), hideBelow: "lg",
      cell: (s) => {
        const end = s.status === "trialing" && s.trial_end ? s.trial_end : s.period_end;
        return <span className="text-sm">{end ? formatDate(end) : "-"}{s.status === "trialing" && s.trial_end && <span className="block text-xs text-muted">{t("subs.trialEnds")}</span>}</span>;
      },
    },
    {
      header: t("subs.users"), align: "right", hideBelow: "sm",
      cell: (s) => <span className="tnum text-sm">{s.users}{s.max_users !== null ? ` / ${s.max_users}` : ""}</span>,
    },
    { header: t("subs.outstanding"), align: "right", hideBelow: "md", cell: (s) => <span className="text-sm">{moneyMap(s.outstanding)}</span> },
    { header: t("subs.lastActivity"), hideBelow: "lg", cell: (s) => <span className="text-sm">{s.last_activity ? formatDate(s.last_activity, true) : "-"}</span> },
  ];

  const total = list.data?.total ?? 0;
  const items = list.data?.items;
  return (
    <>
      <PageHeader title={t("subs.title")} description={t("subs.description")} />
      <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label={t("subs.quickFilters")}>
        {FLAGS.map((f) => (
          <Button key={f} size="sm" variant={filters.flag === f ? "primary" : "secondary"} aria-pressed={filters.flag === f} onClick={() => change({ flag: filters.flag === f ? "" : f })}>
            {t(`subs.flags.${f}`)}
          </Button>
        ))}
        {hasFilters(filters) && <Button size="sm" variant="ghost" onClick={() => { setTyped(""); change({ ...NO_FILTERS }); }}>{t("subs.clear")}</Button>}
      </div>
      <DataTable
        rows={items}
        columns={columns}
        rowKey={(s) => s.id}
        rowHref={(s) => `/operator/subscribers/${encodeURIComponent(s.code)}`}
        loading={list.isPending}
        error={list.isError ? list.error.message : null}
        onRetry={() => void list.refetch()}
        empty={{ title: hasFilters(effective) ? t("subs.noMatch") : t("subs.empty"), hint: hasFilters(effective) ? t("subs.noMatchHint") : t("subs.emptyHint") }}
        toolbar={(
          <>
            <Input aria-label={t("subs.search")} placeholder={t("subs.search")} value={typed} onChange={(e) => { setTyped(e.target.value); setPage(0); }} onBlur={() => change({})} className="w-60" />
            <Select aria-label={t("subs.filterStatus")} value={filters.status} onChange={(e) => change({ status: e.target.value })} className="w-40">
              <option value="">{t("subs.allStatuses")}</option>
              {SUBSCRIPTION_STATUSES.map((s) => <option key={s} value={s}>{t(`status.${s}`)}</option>)}
            </Select>
            <Select aria-label={t("subs.filterPlan")} value={filters.plan} onChange={(e) => change({ plan: e.target.value })} className="w-40">
              <option value="">{t("subs.allPlans")}</option>
              {(plans.data ?? []).map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
            </Select>
            <Select aria-label={t("subs.filterEdition")} value={filters.edition} onChange={(e) => change({ edition: e.target.value })} className="w-40">
              <option value="">{t("subs.allEditions")}</option>
              {(editions.data ?? []).map((e) => <option key={e.id} value={e.id}>{e.title}</option>)}
            </Select>
            <Input aria-label={t("subs.filterCountry")} placeholder={t("subs.filterCountry")} value={filters.country} maxLength={2} onChange={(e) => change({ country: e.target.value })} className="w-24 uppercase" />
          </>
        )}
        footer={(
          <>
            {list.data && <p className="border-t border-line px-4 py-2 text-xs text-muted">{t("subs.total", { count: total })}</p>}
            <Pager page={page} onPage={setPage} hasNext={page * PAGE_SIZE + (items?.length ?? 0) < total} count={items?.length ?? 0} />
          </>
        )}
      />
    </>
  );
}
