import { BellOff, Pencil, HandCoins } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router-dom";

import {
  api, Badge, Button, Card, DetailList, ErrorState, Menu, PageHeader, Skeleton, SlotContent, Tabs, unwrap, useCan, useQuery, useSlot, useTranslation,
} from "@/sdk";

import { AccountTab } from "../components/AccountTab";
import { ContactsCard } from "../components/ContactsCard";
import { CreditTab } from "../components/CreditTab";
import { CustomerForm } from "../components/CustomerForm";
import { DoNotContact } from "../components/DoNotContact";
import { FollowUps } from "../components/FollowUps";
import { ReceivePayment } from "../components/ReceivePayment";
import { useReceivables } from "../components/useReceivables";
import { customerTone } from "../logic";
import { CUSTOMER_TABS } from "../public";

/** One customer: details and contacts, credit, follow-ups, their account (when Point of sale is on), and tabs other modules add. */
export default function CustomerPage() {
  const { t } = useTranslation("crm");
  const { customerId = "" } = useParams();
  const canManage = useCan("customers.manage");
  const { canView, canReceive } = useReceivables();
  const slotTabs = useSlot(CUSTOMER_TABS);
  const [tab, setTab] = useState("details");
  const [editing, setEditing] = useState(false);
  const [receiving, setReceiving] = useState(false);
  const [optOut, setOptOut] = useState(false);
  const q = useQuery({ queryKey: ["customer", customerId], queryFn: () => unwrap(api.GET("/api/v1/crm/customers/{customer_id}", { params: { path: { customer_id: customerId } } })) });
  const c = q.data;

  if (q.error) return <ErrorState title={t("notFoundTitle")} message={q.error.message} onRetry={() => void q.refetch()} />;
  if (!c) return <Skeleton className="h-40 w-full" />;

  const tabs = [
    { id: "details", label: t("details") },
    { id: "credit", label: t("credit") },
    { id: "followUps", label: t("followUps") },
    ...(canView ? [{ id: "account", label: t("account") }] : []),
    ...slotTabs.map((s, i) => ({ id: `slot-${i}`, label: s.label ? t(s.label) : s.unit })),
  ];
  const slot = tab.startsWith("slot-") ? slotTabs[Number(tab.slice(5))] : undefined;

  return (
    <>
      <PageHeader back={{ to: "/customers", label: t("back") }} title={c.name}
        description={<span className="flex flex-wrap items-center gap-2"><span className="font-mono">{c.code}</span><Badge tone={customerTone(c.status)}>{t(`statuses.${c.status}`, c.status)}</Badge></span>}
        actions={
          <>
            {canReceive && <Button onClick={() => setReceiving(true)}><HandCoins className="h-4 w-4" />{t("receivePayment")}</Button>}
            {canManage && <Button variant="secondary" onClick={() => setEditing(true)}><Pencil className="h-4 w-4" />{t("edit")}</Button>}
            {canManage && <Menu label={t("more")} trigger={t("more")} items={[{ label: t("doNotContact"), icon: <BellOff className="h-4 w-4" />, onSelect: () => setOptOut(true) }]} />}
          </>
        } />
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === "details" && (
        <div className="space-y-4">
          <Card>
            <DetailList items={[
              { label: t("kind"), value: t(`kinds.${c.kind}`, c.kind) },
              { label: t("phone"), value: c.phone },
              { label: t("email"), value: c.email },
              { label: t("taxId"), value: c.tax_id },
              { label: t("group"), value: c.customer_group },
              { label: t("terms"), value: t("days", { count: c.payment_terms_days }) },
            ]} />
          </Card>
          <ContactsCard customerId={c.id} companyId={c.company_id} />
        </div>
      )}
      {tab === "credit" && <CreditTab customer={c} />}
      {tab === "followUps" && <FollowUps about={{ type: "customer", id: c.id }} />}
      {tab === "account" && canView && <AccountTab customer={c} />}
      {slot && <Card><SlotContent contribution={slot} props={{ customerId: c.id, companyId: c.company_id }} /></Card>}
      <CustomerForm open={editing} onClose={() => setEditing(false)} customer={c} />
      {canReceive && <ReceivePayment open={receiving} onClose={() => setReceiving(false)} customer={c} />}
      <DoNotContact open={optOut} onClose={() => setOptOut(false)} customerId={c.id} name={c.name} />
    </>
  );
}
