import { Gift, UserPlus } from "lucide-react";
import { useState } from "react";

import {
  api, Alert, Badge, Button, DataTable, formatDate, Input, monthStart, money, PageHeader, Pager, Select, Stat, Switch, Tabs, unwrap, useCan, useCompany, useCurrency,
  useDebounced, usePagedList, useQuery, useTranslation,
} from "@/sdk";

import { SetupCard } from "../components/SetupCard";
import { MemberForm } from "../components/MemberForm";
import { PackageDrawer } from "../components/PackageDrawer";
import { SellPackageForm } from "../components/SellPackageForm";
import { credits, memberTone, packageTone } from "../logic";
import { arrearsPath, memberPath, personPath, recurringPath } from "../public";
import { usePlans } from "../hooks";
import type { SoldPackage } from "../hooks";

const MEMBER_STATUSES = ["active", "paused", "frozen", "cancelled", "expired"] as const;
const PACKAGE_STATUSES = ["active", "expired", "refunded"] as const;

function monthEnd(): string {
  const d = new Date(`${monthStart()}T00:00:00`);
  d.setMonth(d.getMonth() + 1, 0);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Members of the business and the packages they bought: the figures to watch, then the lists. */
export default function MembersPage() {
  const { t } = useTranslation("memberships");
  const canManage = useCan("memberships.manage");
  const { company } = useCompany();
  const currency = useCurrency(company?.id);
  const [tab, setTab] = useState<"members" | "packages">("members");
  const [signing, setSigning] = useState(false);
  const [selling, setSelling] = useState(false);
  const [status, setStatus] = useState("");
  const [planId, setPlanId] = useState("");
  const [renewing, setRenewing] = useState(false);
  const [late, setLate] = useState(false);
  const [search, setSearch] = useState("");
  const typed = useDebounced(search.trim(), 300);
  const searching = typed.length >= 2;
  const [pkgStatus, setPkgStatus] = useState("active");
  const [openPackage, setOpenPackage] = useState<SoldPackage | null>(null);
  const plans = usePlans(company?.id);
  const summary = useQuery({ queryKey: ["memberships", "summary"], queryFn: () => unwrap(api.GET("/api/v1/memberships/summary", { params: { query: {} } })) });
  const s = summary.data;

  const members = usePagedList(["memberships", "members", status, planId, renewing, late], (limit, offset) =>
    unwrap(api.GET("/api/v1/memberships/members", { params: { query: {
      status: (status || undefined) as "active" | undefined, plan_id: planId || undefined,
      past_due: late ? true : undefined, renewing_from: renewing ? monthStart() : undefined, renewing_to: renewing ? monthEnd() : undefined, limit, offset } } })), 25, tab === "members" && !searching);
  const found = usePagedList(["memberships", "profiles", company?.id, typed], (limit, offset) =>
    unwrap(api.GET("/api/v1/memberships/profiles", { params: { query: { company_id: company?.id ?? "", search: typed, limit, offset } } })), 25, tab === "members" && searching && !!company);
  const packages = usePagedList(["memberships", "sold", pkgStatus], (limit, offset) =>
    unwrap(api.GET("/api/v1/memberships/sold-packages", { params: { query: { status: (pkgStatus || undefined) as "active" | undefined, limit, offset } } })), 25, tab === "packages");
  const attention = (s?.failed_runs ?? 0) + (s?.drafts_waiting ?? 0);

  return (
    <>
      <PageHeader title={t("menu")} description={t("hint")}
        actions={canManage && (<><Button variant="secondary" onClick={() => setSelling(true)}><Gift className="h-4 w-4" />{t("sellPackage")}</Button>
          <Button onClick={() => setSigning(true)}><UserPlus className="h-4 w-4" />{t("signUp")}</Button></>)} />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label={t("stats.active")} value={s?.active_members ?? 0} loading={summary.isLoading} hint={s?.paused_members ? t("stats.onHold", { count: s.paused_members }) : undefined} />
        <Stat label={t("stats.renewalsMonth")} value={s?.renewals_this_month ?? 0} loading={summary.isLoading} hint={t("stats.renewalsWeek", { count: s?.renewals_next_7_days ?? 0 })} />
        <Stat label={t("stats.expiring")} value={s?.packages_expiring_30_days ?? 0} loading={summary.isLoading} hint={t("stats.expiringHint")} />
        <Stat label={t("stats.late")} value={s?.members_late ?? 0} loading={summary.isLoading} tone={(s?.members_late ?? 0) > 0 ? "bad" : undefined} to={(s?.members_late ?? 0) > 0 ? arrearsPath : undefined}
          hint={t("stats.visitsToday", { count: s?.visits_today ?? 0 })} />
        <Stat label={t("stats.attention")} value={attention} loading={summary.isLoading} tone={attention > 0 ? "bad" : undefined} to={attention > 0 ? recurringPath : undefined}
          hint={attention > 0 ? t("stats.attentionHint") : t("stats.allClear")} />
      </div>
      {summary.error && <Alert tone="warn" className="mb-4">{summary.error.message}</Alert>}
      <SetupCard companyId={company?.id ?? ""} onSignUp={() => setSigning(true)} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "members", label: t("tabs.members") }, { id: "packages", label: t("tabs.packages") }]} />
      {tab === "members" && (
        <Input className="mb-3 max-w-md" type="search" aria-label={t("searchLabel")} placeholder={t("searchPlaceholder")} value={search} onChange={(e) => setSearch(e.target.value)} />
      )}
      {tab === "members" && searching && (
        <DataTable
          rows={found.rows} loading={found.query.isLoading} error={found.query.error?.message} onRetry={() => void found.query.refetch()} rowKey={(p) => p.id} rowHref={(p) => personPath(p.customer_id)}
          empty={{ title: t("noPersonFound"), hint: t("noPersonFoundHint") }}
          columns={[
            { header: t("member"), cell: (p) => <span><span className="font-medium">{p.customer_name ?? p.number}</span><span className="block font-mono text-xs text-muted">{p.number}{p.card_number ? ` · ${p.card_number}` : ""}</span></span> },
            { header: t("phone"), hideBelow: "sm", cell: (p) => p.phone ?? "—" },
            { header: t("status"), cell: (p) => <Badge tone={p.access_blocked ? "bad" : p.lifecycle === "trial" ? "info" : "neutral"}>{p.access_blocked ? t("person.entryStopped") : t(`lifecycle.${p.lifecycle}`, p.lifecycle)}</Badge> },
            { header: t("person.lastVisitShort"), hideBelow: "md", cell: (p) => (p.last_visit_on ? formatDate(p.last_visit_on) : "—") },
          ]}
          footer={<Pager page={found.page} onPage={found.setPage} hasNext={found.hasNext} count={found.rows?.length ?? 0} />} />
      )}
      {tab === "members" && !searching && (
        <DataTable
          rows={members.rows} loading={members.query.isLoading} error={members.query.error?.message} onRetry={() => void members.query.refetch()}
          rowKey={(m) => m.id} rowHref={(m) => memberPath(m.id)}
          toolbar={
            <>
              <Select className="w-40" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">{t("allStatuses")}</option>
                {MEMBER_STATUSES.map((x) => <option key={x} value={x}>{t(`memberStatus.${x}`)}</option>)}
              </Select>
              <Select className="w-44" aria-label={t("plan")} value={planId} onChange={(e) => setPlanId(e.target.value)}>
                <option value="">{t("allPlans")}</option>
                {plans.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </Select>
              <Switch checked={renewing} onChange={setRenewing} label={t("renewingThisMonth")} />
              <Switch checked={late} onChange={setLate} label={t("lateOnly")} />
            </>
          }
          empty={{
            title: status || planId || renewing || late ? t("noMatch") : t("empty"), hint: status || planId || renewing || late ? undefined : t("emptyHint"),
            action: canManage && !status && !planId && !renewing && !late ? <Button onClick={() => setSigning(true)}>{t("signUp")}</Button> : undefined,
          }}
          columns={[
            { header: t("member"), sortValue: (m) => m.customer_name ?? "", cell: (m) => <span><span className="font-medium">{m.customer_name ?? m.number}</span><span className="block font-mono text-xs text-muted">{m.number}</span></span> },
            { header: t("plan"), hideBelow: "sm", sortValue: (m) => m.plan_name, cell: (m) => m.plan_name },
            { header: t("status"), cell: (m) => (
              <span className="flex flex-wrap gap-1">
                <Badge tone={memberTone(m.status)}>{t(`memberStatus.${m.status}`, m.status)}</Badge>
                {m.is_trial && <Badge tone="info">{t("badge.trial")}</Badge>}
                {Number(m.arrears) > 0 && <Badge tone="bad">{m.days_late > 0 ? t("badge.lateDays", { count: m.days_late }) : t("badge.owes")}</Badge>}
                {m.plan_kind !== "recurring" && <Badge tone="neutral">{t(`planx.kinds.${m.plan_kind}`, m.plan_kind)}</Badge>}
              </span>) },
            { header: t("nextRenewal"), hideBelow: "md", sortValue: (m) => m.next_renewal_date, cell: (m) => (m.status !== "active" ? "—" : m.cancel_at ? <span className="text-warn">{t("endsOn", { date: formatDate(m.cancel_at) })}</span> : formatDate(m.next_renewal_date)) },
            { header: t("creditsLeft"), hideBelow: "md", align: "right", cell: (m) => (Number(m.credits_per_period) > 0 || Number(m.balance) !== 0 ? credits(m.balance) : "—") },
            { header: t("fee"), hideBelow: "lg", align: "right", cell: (m) => `${money(m.price, currency)} / ${t(`intervalShort.${m.billing_interval}`)}` },
          ]}
          footer={<Pager page={members.page} onPage={members.setPage} hasNext={members.hasNext} count={members.rows?.length ?? 0} />}
        />
      )}
      {tab === "packages" && (
        <DataTable
          rows={packages.rows} loading={packages.query.isLoading} error={packages.query.error?.message} onRetry={() => void packages.query.refetch()}
          rowKey={(p) => p.id}
          toolbar={
            <Select className="w-40" aria-label={t("status")} value={pkgStatus} onChange={(e) => setPkgStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>
              {PACKAGE_STATUSES.map((x) => <option key={x} value={x}>{t(`packageStatus.${x}`)}</option>)}
            </Select>
          }
          empty={{ title: pkgStatus ? t("noPackagesMatch") : t("noPackagesSold"), hint: pkgStatus ? undefined : t("noPackagesSoldHint"),
            action: canManage && !pkgStatus ? <Button onClick={() => setSelling(true)}>{t("sellPackage")}</Button> : undefined }}
          columns={[
            { header: t("package"), sortValue: (p) => p.name, cell: (p) => (
              <button type="button" className="text-left" onClick={() => setOpenPackage(p)}>
                <span className="font-medium text-brand-strong hover:underline">{p.name}</span><span className="block font-mono text-xs text-muted">{p.number}</span>
              </button>) },
            { header: t("customer"), sortValue: (p) => p.customer_name ?? "", cell: (p) => p.customer_name ?? "—" },
            { header: t("creditsLeft"), align: "right", cell: (p) => t("ofTotal", { left: credits(p.balance), total: credits(p.credits) }) },
            { header: t("expires"), hideBelow: "sm", sortValue: (p) => p.expires_on ?? "9999", cell: (p) => (p.expires_on ? formatDate(p.expires_on) : t("neverExpires")) },
            { header: t("status"), cell: (p) => <Badge tone={packageTone(p.status)}>{t(`packageStatus.${p.status}`, p.status)}</Badge> },
          ]}
          footer={<Pager page={packages.page} onPage={packages.setPage} hasNext={packages.hasNext} count={packages.rows?.length ?? 0} />}
        />
      )}
      <MemberForm open={signing} onClose={() => setSigning(false)} />
      <SellPackageForm open={selling} onClose={() => setSelling(false)} />
      <PackageDrawer item={openPackage} onClose={() => setOpenPackage(null)} />
    </>
  );
}
