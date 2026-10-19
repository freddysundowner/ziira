import { UserPlus } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  api, Alert, Badge, Button, EmptyState, ErrorState, formatDate, PageHeader, Skeleton, Tabs, unwrap, useCan, useQuery, useTranslation,
} from "@/sdk";

import type { Member } from "../hooks";
import { memberTone } from "../logic";
import { MemberActions } from "./MemberActions";
import { MemberForm } from "./MemberForm";
import { PersonPhoto } from "./PersonPhoto";
import { MoneyTab } from "./MoneyTab";
import { OverviewTab } from "./OverviewTab";
import { ProfileTab } from "./ProfileTab";
import { VisitsTab } from "./VisitsTab";
import { useProfile, useProfilePhotos } from "./useProfile";

type Tab = "overview" | "money" | "visits" | "profile";
const TABS: readonly Tab[] = ["overview", "money", "visits", "profile"];

/** Picks the membership to show: a live one first, newest first. */
function bestMembership(rows: readonly Member[]): Member | undefined {
  const live = (m: Member) => (m.status === "active" ? 0 : m.status === "paused" || m.status === "frozen" ? 1 : 2);
  return [...rows].sort((a, b) => live(a) - live(b) || b.start_date.localeCompare(a.start_date))[0];
}

/**
 * The page of one person at the club, in four tabs: Overview (membership, credits, holds, plan changes, guests), Money (what is owed,
 * payments, write-offs, credit and points), Visits and Profile (photo, contact, household, terms, measurements). Opened by a
 * membership or by a customer.
 */
export function PersonView({ memberId, customerId }: { memberId?: string; customerId?: string }) {
  const { t } = useTranslation("memberships");
  const canManage = useCan("memberships.manage");
  const [params, setParams] = useSearchParams();
  const asked = params.get("tab") as Tab | null;
  const tab: Tab = asked && TABS.includes(asked) ? asked : "overview";
  const setTab = (next: Tab) => setParams(next === "overview" ? {} : { tab: next }, { replace: true });
  const [signing, setSigning] = useState(false);

  const byId = useQuery({
    enabled: !!memberId, queryKey: ["memberships", "member", memberId],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/members/{member_id}", { params: { path: { member_id: memberId ?? "" } } })),
  });
  const owner = customerId ?? byId.data?.customer_id ?? "";
  const byCustomer = useQuery({
    enabled: !!customerId, queryKey: ["memberships", "member-of", customerId],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/members", { params: { query: { customer_id: customerId, limit: 20 } } })),
  });
  const profile = useProfile(owner);
  const photos = useProfilePhotos(profile.data);

  const loadError = byId.error ?? byCustomer.error ?? profile.error;
  if (loadError) return <ErrorState title={t("notFoundTitle")} message={loadError.message} onRetry={() => { void byId.refetch(); void byCustomer.refetch(); void profile.refetch(); }} />;
  const resolving = memberId ? byId.isLoading : byCustomer.isLoading;
  if (resolving || profile.isLoading || !owner) return <Skeleton className="h-40 w-full" />;

  const m = memberId ? byId.data : bestMembership(byCustomer.data ?? []);
  const p = profile.data;
  const name = p?.customer_name ?? m?.customer_name ?? p?.number ?? m?.number ?? "";
  if (!m && !p) {
    return (
      <>
        <PageHeader back={{ to: "/memberships", label: t("back") }} title={t("person.notAMember")} />
        <EmptyState title={t("person.notAMember")} hint={t("person.notAMemberHint")}
          action={canManage ? <Button onClick={() => setSigning(true)}><UserPlus className="h-4 w-4" />{t("signUp")}</Button> : undefined} />
        <MemberForm open={signing} onClose={() => setSigning(false)} customerId={owner} />
      </>
    );
  }
  const companyId = m?.company_id ?? p?.company_id ?? "";
  const late = m && Number(m.arrears) > 0 ? m.days_late : null;

  return (
    <>
      <PageHeader back={{ to: "/memberships", label: t("back") }}
        title={(
          <span className="flex items-center gap-3">
            <PersonPhoto url={photos.mainUrl} name={name} size="md" />
            <span className="min-w-0 truncate">{name}</span>
          </span>
        )}
        description={(
          <span className="flex flex-wrap items-center gap-2">
            {p && <span className="font-mono">{p.number}</span>}
            {m && <Badge tone={memberTone(m.status)}>{t(`memberStatus.${m.status}`, m.status)}</Badge>}
            {m?.is_trial && <Badge tone="info">{t("badge.trial")}</Badge>}
            {late !== null && <Badge tone="bad">{late > 0 ? t("badge.lateDays", { count: late }) : t("badge.owes")}</Badge>}
            {p?.access_blocked && <Badge tone="bad">{t("person.entryStopped")}</Badge>}
            {m && <span>{m.plan_name}</span>}
            {p?.last_visit_on && <span className="text-muted">{t("person.lastVisit", { date: formatDate(p.last_visit_on) })}</span>}
          </span>
        )}
        actions={m ? <MemberActions member={m} /> : canManage ? <Button onClick={() => setSigning(true)}><UserPlus className="h-4 w-4" />{t("signUp")}</Button> : undefined} />
      {p?.access_blocked && <Alert tone="bad" className="mb-4">{t("person.entryStoppedBanner", { reason: p.block_reason ?? "—" })}</Alert>}
      <Tabs value={tab} onChange={setTab} tabs={TABS.map((id) => ({ id, label: t(`person.tabs.${id}`) }))} />
      {tab === "overview" && <OverviewTab member={m} customerId={owner} companyId={companyId} />}
      {tab === "money" && <MoneyTab member={m} customerId={owner} companyId={companyId} />}
      {tab === "visits" && <VisitsTab customerId={owner} companyId={companyId} profile={p ?? null} />}
      {tab === "profile" && <ProfileTab customerId={owner} companyId={companyId} profile={p ?? null} photos={photos.files} member={m} />}
      <MemberForm open={signing} onClose={() => setSigning(false)} customerId={owner} />
    </>
  );
}
