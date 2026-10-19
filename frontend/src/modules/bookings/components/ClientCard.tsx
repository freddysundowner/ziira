import { useEffect, useState } from "react";

import {
  Alert, api, Attachments, Badge, Button, Card, CustomFieldsForm, DetailList, Drawer, ErrorState, formatDate, money, Skeleton, toFormValues, toPayload, toast, unwrap, useCan,
  useCurrency, useCustomFieldDefs, useMutation, useQuery, useTranslation, validateCustomValues, type CustomValues,
} from "@/sdk";

import { useRefreshBookings } from "../hooks";

/** Everything the desk wants to know about a client: history, usual staff, fees, credit, the business's own fields and photos. */
export function ClientCard({ customerId, companyId, name, onClose }: { customerId: string | null; companyId: string; name?: string | null; onClose: () => void }) {
  const { t } = useTranslation("bookings");
  const canManage = useCan("bookings.manage");
  const refresh = useRefreshBookings();
  const currency = useCurrency(companyId);
  const card = useQuery({
    queryKey: ["bookings", "client-card", customerId], enabled: !!customerId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/clients/{customer_id}/card", { params: { path: { customer_id: customerId as string }, query: { company_id: companyId } } })),
  });
  const defs = useCustomFieldDefs("bookings.client", companyId, !!customerId);
  const saved = card.data?.values ?? {};
  const [values, setValues] = useState<CustomValues>({});
  useEffect(() => { if (defs.data) setValues(toFormValues(defs.data, saved)); }, [defs.data, card.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const problems = defs.data ? validateCustomValues(defs.data, values) : {};
  const save = useMutation({
    mutationFn: () => unwrap(api.PUT("/api/v1/bookings/clients/{customer_id}/fields", {
      params: { path: { customer_id: customerId as string }, query: { company_id: companyId } },
      body: { values: toPayload(defs.data ?? [], values, toFormValues(defs.data ?? [], saved)) } })),
    onSuccess: () => { void card.refetch(); void refresh(); toast(t("clientCard.saved"), "ok"); },
  });
  const c = card.data;

  return (
    <Drawer open={!!customerId} onClose={onClose} title={name ? t("clientCard.titleFor", { name }) : t("clientCard.title")}>
      {card.isLoading && <div className="space-y-3"><Skeleton className="h-6 w-40" /><Skeleton className="h-32 w-full" /></div>}
      {card.error && <ErrorState message={card.error.message} onRetry={() => void card.refetch()} />}
      {c && (
        <div className="space-y-5">
          {c.patch_test && <Alert tone="warn">{c.patch_test}</Alert>}
          {c.open_fees.length > 0 && <Alert tone="warn">{t("clientCard.owesFees", { count: c.open_fees.length })}</Alert>}
          <DetailList items={[
            { label: t("clientCard.visits"), value: String(c.visits) },
            { label: t("clientCard.lastVisit"), value: c.last_visit ? formatDate(c.last_visit) : "—" },
            { label: t("clientCard.noShows"), value: String(c.no_shows) },
            { label: t("clientCard.usualStaff"), value: c.usual_staff.map((s) => `${s.name} (${s.visits})`).join(", ") || "—" },
            ...(c.membership ? [{ label: t("clientCard.membership"), value: `${c.membership.plan} · ${t("clientCard.credits", { count: Number(c.membership.credits) })}` }] : []),
            ...(c.credit != null && !c.membership ? [{ label: t("clientCard.credit"), value: String(c.credit) }] : []),
            ...(c.on_account && Number(c.on_account) > 0 ? [{ label: t("clientCard.onAccount"), value: money(c.on_account, currency) }] : []),
          ]} />
          {defs.data && defs.data.length > 0 && (
            <Card title={t("clientCard.details")}>
              <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (Object.keys(problems).length === 0) save.mutate(); }}>
                <CustomFieldsForm fields={defs.data} values={values} problems={problems} readOnly={!canManage} onChange={(key, value) => setValues((v) => ({ ...v, [key]: value }))} />
                {canManage && <Button type="submit" loading={save.isPending} disabled={Object.keys(problems).length > 0}>{t("save")}</Button>}
              </form>
            </Card>
          )}
          <Card title={t("clientCard.history")}>
            {c.history.length === 0 ? <p className="text-sm text-muted">{t("clientCard.noHistory")}</p> : (
              <ul className="divide-y divide-line text-sm">
                {c.history.map((h) => (
                  <li key={h.appointment_id} className="flex items-center justify-between gap-2 py-2">
                    <span><span className="font-medium">{h.service}</span><span className="block text-xs text-muted">{formatDate(h.starts_at)} · {h.number}</span></span>
                    <Badge tone={h.status === "completed" ? "ok" : h.status === "no_show" ? "bad" : "neutral"}>{t(`status.${h.status}`, h.status)}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Attachments entityType="bookings.client" entityId={c.customer_id} title={t("clientCard.photos")} />
        </div>
      )}
    </Drawer>
  );
}
