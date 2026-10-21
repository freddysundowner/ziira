import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { ErrorState, Menu, type MenuEntry, PageHeader, type Schemas, Skeleton, Tabs, toast, useTranslation } from "@/sdk";

import { opApi, opDownload, opUnwrap, saveBlob } from "../../client";
import { SubscriptionBadge } from "../../components/bits";
import { ChangeConfirm } from "../../components/ChangeConfirm";
import { ReasonDialog } from "../../components/ReasonDialog";
import { availableActions, type SubscriberAction } from "../../helpers/subscribers";
import { useOperatorMe } from "../../me";
import { StepUpCancelled, useStepUp } from "../../stepUp";
import { InvoiceFormDialog, useRefreshOperator } from "../billing/invoiceDialogs";
import { CancelDialog, ChangePlanDialog, CompDialog, CouponDialog, DeleteDialog, ExtendTrialDialog, StartSubscriptionDialog } from "./actionDialogs";
import { AuditTab } from "./AuditTab";
import { BillingTab } from "./BillingTab";
import { OverviewTab } from "./OverviewTab";
import { SupportTab } from "./SupportTab";
import { TimelineTab } from "./TimelineTab";
import { UnitsTab } from "./UnitsTab";

type Detail = Schemas["SubscriberDetail"];
const TABS = ["overview", "billing", "timeline", "units", "support", "audit"] as const;
type Tab = (typeof TABS)[number];

export default function SubscriberPage() {
  const { t } = useTranslation("operator");
  const code = useParams().code ?? "";
  const detail = useQuery({
    queryKey: ["operator", "subscriber", code],
    queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/subscribers/{code}", { params: { path: { code } } })),
  });
  if (detail.isPending) return <div className="space-y-3"><Skeleton className="h-8 w-64" /><Skeleton className="h-40 w-full" /></div>;
  if (detail.isError) return <ErrorState title={t("subscriber.loadFailed")} message={detail.error.message} onRetry={() => void detail.refetch()} />;
  return <SubscriberView d={detail.data} />;
}

function SubscriberView({ d }: { d: Detail }) {
  const { t } = useTranslation("operator");
  const queryClient = useQueryClient();
  const refresh = useRefreshOperator();
  const stepUp = useStepUp();
  const me = useOperatorMe();
  const [params, setParams] = useSearchParams();
  const tab: Tab = (TABS as readonly string[]).includes(params.get("tab") ?? "") ? (params.get("tab") as Tab) : "overview";
  const [dialog, setDialog] = useState<SubscriberAction | null>(null);

  const permissions = me.data?.permissions ?? [];
  const actions = availableActions(d, (p) => permissions.includes(p));

  const saved = (message?: string) => (detail: Detail) => {
    queryClient.setQueryData(["operator", "subscriber", d.code], detail);
    if (message) toast(message, "ok");
    refresh();
  };
  const close = () => setDialog(null);
  const path = { params: { path: { code: d.code } } };

  const exportData = async () => {
    try {
      const blob = await stepUp(() => opDownload(`/api/v1/operator/subscribers/${encodeURIComponent(d.code)}/export`));
      saveBlob(blob, `subscriber-${d.code}.json`);
      toast(t("subscriber.exported"), "ok");
    } catch (error) {
      if (!(error instanceof StepUpCancelled)) toast((error as Error).message || t("subscriber.exportFailed"), "bad");
    }
  };

  const entries: MenuEntry[] = actions.map((a) => ({
    label: t(`subscriber.actions.${a}`),
    danger: a === "delete" || a === "cancel" || a === "suspend",
    onSelect: () => (a === "export" ? void exportData() : setDialog(a)),
  }));
  const primary = actions.includes("start") ? "start" : actions.includes("changePlan") ? "changePlan" : null;
  const menuItems = entries.filter((_, i) => actions[i] !== primary);

  return (
    <>
      <PageHeader
        title={d.name}
        description={<span className="inline-flex flex-wrap items-center gap-2"><span className="font-mono">{d.code}</span><SubscriptionBadge status={d.status} /></span>}
        back={{ to: "/operator/subscribers", label: t("subscriber.back") }}
        actions={actions.length > 0 ? (
          <>
            {primary && (
              <button type="button" onClick={() => setDialog(primary)} className="btn-gradient inline-flex h-9 items-center rounded-lg px-3.5 text-sm font-medium ">
                {t(`subscriber.actions.${primary}`)}
              </button>
            )}
            {menuItems.length > 0 && (
              <Menu label={t("subscriber.moreActions")} items={menuItems}
                trigger={<span className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line bg-surface px-3.5 text-sm font-medium shadow-card hover:bg-sunken">{t("subscriber.moreActions")} <ChevronDown className="h-4 w-4" /></span>} />
            )}
          </>
        ) : undefined}
      />

      <Tabs<Tab>
        tabs={TABS.map((id) => ({ id, label: t(`subscriber.tabs.${id}`), count: id === "billing" ? d.invoices.length : id === "timeline" ? d.timeline.length : undefined }))}
        value={tab}
        onChange={(id) => setParams(id === "overview" ? {} : { tab: id }, { replace: true })}
      />
      {tab === "overview" && <OverviewTab d={d} onSaved={saved()} />}
      {tab === "billing" && <BillingTab d={d} onSaved={saved()} />}
      {tab === "timeline" && <TimelineTab events={d.timeline} />}
      {tab === "units" && <UnitsTab code={d.code} />}
      {tab === "support" && <SupportTab code={d.code} />}
      {tab === "audit" && <AuditTab lines={d.audit_trail} />}

      {dialog === "start" && <StartSubscriptionDialog code={d.code} onDone={saved(t("subscriber.start.done"))} onClose={close} />}
      {dialog === "changePlan" && <ChangePlanDialog code={d.code} currentPlan={d.subscription?.plan_name} onDone={saved(t("subscriber.changePlan.done"))} onClose={close} />}
      {dialog === "extendTrial" && <ExtendTrialDialog code={d.code} trialEnd={d.subscription?.trial_end} onDone={saved(t("subscriber.trial.done"))} onClose={close} />}
      {dialog === "comp" && <CompDialog code={d.code} onDone={saved(t("subscriber.comp.done"))} onClose={close} />}
      {dialog === "coupon" && <CouponDialog code={d.code} onDone={saved(t("subscriber.coupon.done"))} onClose={close} />}
      {dialog === "cancel" && <CancelDialog code={d.code} onDone={saved(t("subscriber.cancel.done"))} onClose={close} />}
      {dialog === "delete" && <DeleteDialog code={d.code} onDone={saved(t("subscriber.delete.done"))} onClose={close} />}
      {dialog === "issueInvoice" && <InvoiceFormDialog tenantCode={d.code} onClose={close} />}
      {dialog === "syncPlan" && (
        <ChangeConfirm title={t("subscriber.sync.title")} message={<p>{t("subscriber.sync.message")}</p>} confirmLabel={t("subscriber.sync.submit")}
          run={() => opUnwrap(opApi.POST("/api/v1/operator/subscribers/{code}/sync-plan", path))} onDone={saved(t("subscriber.sync.done"))} onClose={close} />
      )}
      {dialog === "uncancel" && (
        <ChangeConfirm title={t("subscriber.uncancel.title")} message={<p>{t("subscriber.uncancel.message")}</p>} confirmLabel={t("subscriber.uncancel.submit")}
          run={() => opUnwrap(opApi.POST("/api/v1/operator/subscribers/{code}/uncancel", path))} onDone={saved(t("subscriber.uncancel.done"))} onClose={close} />
      )}
      {dialog === "suspend" && (
        <ReasonDialog title={t("subscriber.suspend.title")} intro={t("subscriber.suspend.message")} confirmLabel={t("subscriber.suspend.submit")} danger
          run={(reason) => opUnwrap(opApi.POST("/api/v1/operator/subscribers/{code}/suspend", { ...path, body: { reason } }))} onDone={saved(t("subscriber.suspend.done"))} onClose={close} />
      )}
      {dialog === "reactivate" && (
        <ReasonDialog title={t("subscriber.reactivate.title")} intro={t("subscriber.reactivate.message")} confirmLabel={t("subscriber.reactivate.submit")} required={false} label={t("common.reasonOptional")}
          run={(reason) => opUnwrap(opApi.POST("/api/v1/operator/subscribers/{code}/reactivate", { ...path, body: { reason: reason || null } }))} onDone={saved(t("subscriber.reactivate.done"))} onClose={close} />
      )}
    </>
  );
}
