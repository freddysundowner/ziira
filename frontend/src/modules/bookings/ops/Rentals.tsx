import { Plus } from "lucide-react";
import { useEffect, useState } from "react";

import { api, Badge, Button, Card, DataTable, Drawer, Field, formatDate, FormGrid, Input, money, Select, ConfirmDialog, toast, today, unwrap, useMutation, useQuery, useTranslation, type Schemas } from "@/sdk";

import { useRefreshBookings, useResources } from "../hooks";
import { ClientPicker } from "./ClientPicker";

type Rental = Schemas["RentalOut"];

/** Chair and room rent: what a renter pays every week or month; the bill is made by the system. */
export function Rentals({ companyId, branchId, currency }: { companyId: string; branchId: string; currency?: string }) {
  const { t } = useTranslation("bookings");
  const refresh = useRefreshBookings();
  const [adding, setAdding] = useState(false);
  const [ending, setEnding] = useState<Rental | null>(null);
  const resources = useResources(branchId, false);
  const list = useQuery<Rental[]>({
    queryKey: ["bookings", "rentals", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/rentals", { params: { query: { company_id: companyId } } })),
  });
  const end = useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/api/v1/bookings/rentals/{rental_id}/end", { params: { path: { rental_id: id } }, body: {} })),
    onSuccess: () => { void refresh(); setEnding(null); toast(t("staffPay.rent.ended"), "ok"); },
  });

  return (
    <Card title={t("staffPay.rent.title")} description={t("staffPay.rent.hint")} actions={<Button size="sm" onClick={() => setAdding(true)}><Plus className="h-4 w-4" />{t("staffPay.rent.add")}</Button>} flush>
      <DataTable
        rows={list.data} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()} rowKey={(r) => r.id}
        empty={{ title: t("staffPay.rent.empty"), hint: t("staffPay.rent.emptyHint"), action: <Button onClick={() => setAdding(true)}>{t("staffPay.rent.add")}</Button> }}
        columns={[
          { header: t("staffPay.rent.what"), cell: (r) => (
            <div><p className="font-medium">{r.description}</p>{r.resource_id && <p className="text-xs text-muted">{resources.data?.find((p) => p.id === r.resource_id)?.name}</p>}</div>
          ) },
          { header: t("staffPay.rent.amount"), align: "right", cell: (r) => <span className="tnum">{money(r.amount, currency)} / {t(`staffPay.rent.every.${r.every}`, r.every)}</span> },
          { header: t("staffPay.rent.nextDue"), hideBelow: "sm", cell: (r) => (r.is_active ? formatDate(r.next_due) : "—") },
          { header: t("staffPay.rent.lastBill"), hideBelow: "lg", cell: (r) => r.last_invoice_number ?? "—" },
          { header: t("status.label"), cell: (r) => <Badge tone={r.is_active ? "ok" : "neutral"}>{r.is_active ? t("staffPay.rent.running") : t("staffPay.rent.endedBadge")}</Badge> },
          { header: "", align: "right", cell: (r) => r.is_active && <Button size="sm" variant="ghost" onClick={() => setEnding(r)}>{t("staffPay.rent.end")}</Button> },
        ]}
      />
      <RentalDrawer open={adding} onClose={() => setAdding(false)} companyId={companyId} branchId={branchId} currency={currency} />
      <ConfirmDialog open={!!ending} onClose={() => setEnding(null)} title={t("staffPay.rent.endTitle")} message={t("staffPay.rent.endMessage", { name: ending?.description ?? "" })} danger busy={end.isPending}
        confirmLabel={t("staffPay.rent.end")} onConfirm={() => ending && end.mutate(ending.id)} />
    </Card>
  );
}

function RentalDrawer({ open, onClose, companyId, branchId, currency }: { open: boolean; onClose: () => void; companyId: string; branchId: string; currency?: string }) {
  const { t } = useTranslation("bookings");
  const refresh = useRefreshBookings();
  const resources = useResources(branchId);
  const items = useQuery({
    queryKey: ["bookings", "service-items", companyId], enabled: open && !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/service-items", { params: { query: { company_id: companyId } } })),
  });
  const [client, setClient] = useState("");
  const [item, setItem] = useState("");
  const [amount, setAmount] = useState("");
  const [every, setEvery] = useState<"week" | "month">("month");
  const [start, setStart] = useState(today());
  const [chair, setChair] = useState("");
  useEffect(() => { if (open) { setClient(""); setItem(""); setAmount(""); setEvery("month"); setStart(today()); setChair(""); } }, [open]);

  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/rentals", { body: { company_id: companyId, branch_id: branchId, customer_id: client, product_id: item, amount, every, start_date: start, resource_id: chair || null } })),
    onSuccess: () => { void refresh(); toast(t("staffPay.rent.saved"), "ok"); onClose(); },
  });

  return (
    <Drawer open={open} onClose={onClose} title={t("staffPay.rent.add")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("close")}</Button><Button type="submit" form="rental-form" loading={save.isPending} disabled={!client || !item || !amount || Number(amount) <= 0}>{t("save")}</Button></>}>
      <form id="rental-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <Field label={t("staffPay.rent.renter")} required><ClientPicker companyId={companyId} value={client} placeholder={t("classes.findClient")} onChange={(id) => setClient(id)} /></Field>
        <Field label={t("staffPay.rent.item")} required hint={items.data && items.data.length === 0 ? t("staffPay.rent.noItems") : t("staffPay.rent.itemHint")} error={items.error?.message}>
          <Select value={item} onChange={(e) => setItem(e.target.value)}>
            <option value="">{t("staffPay.rent.pickItem")}</option>
            {(items.data ?? []).map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
          </Select>
        </Field>
        <FormGrid>
          <Field label={`${t("staffPay.rent.amount")}${currency ? ` (${currency})` : ""}`} required><Input type="number" inputMode="decimal" min={0} step="any" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
          <Field label={t("staffPay.rent.everyLabel")}>
            <Select value={every} onChange={(e) => setEvery(e.target.value as "week" | "month")}>
              <option value="week">{t("staffPay.rent.every.week")}</option>
              <option value="month">{t("staffPay.rent.every.month")}</option>
            </Select>
          </Field>
        </FormGrid>
        <Field label={t("staffPay.rent.startDate")}><Input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label={t("staffPay.rent.chair")} hint={t("staffPay.rent.chairHint")}>
          <Select value={chair} onChange={(e) => setChair(e.target.value)}>
            <option value="">{t("staffPay.rent.noChair")}</option>
            {(resources.data ?? []).filter((r) => r.kind === "chair" || r.kind === "room").map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </Select>
        </Field>
      </form>
    </Drawer>
  );
}
