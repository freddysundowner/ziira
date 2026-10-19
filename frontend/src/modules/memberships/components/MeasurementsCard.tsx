import { Trash2 } from "lucide-react";
import { useState } from "react";

import {
  api, Button, Card, DataTable, Field, formatDate, IconButton, Input, NumberInput, toast, today, unwrap, useCan, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

/** Measurements a member chooses to share (weight, waist ...): add one, see them, remove one. */
export function MeasurementsCard({ customerId }: { customerId: string }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const canManage = useCan("memberships.manage");
  const [metric, setMetric] = useState("");
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("");
  const [date, setDate] = useState(today());
  const q = useQuery({ queryKey: ["memberships", "measurements", customerId], queryFn: () => unwrap(api.GET("/api/v1/memberships/customers/{customer_id}/measurements", { params: { path: { customer_id: customerId } } })) });
  const add = useMutation({
    meta: { silent: true }, onError: (e) => toast((e as Error).message, "bad"),
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/customers/{customer_id}/measurements", { params: { path: { customer_id: customerId } }, body: { metric: metric.trim(), value, unit: unit.trim() || null, taken_on: date || null } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["memberships", "measurements"] }); setValue(""); toast(t("measures.added"), "ok"); },
  });
  const remove = useMutation({
    meta: { silent: true }, onError: (e) => toast((e as Error).message, "bad"),
    mutationFn: (id: string) => unwrap(api.DELETE("/api/v1/memberships/measurements/{measurement_id}", { params: { path: { measurement_id: id } } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["memberships", "measurements"] }); toast(t("measures.removed"), "ok"); },
  });
  return (
    <Card title={t("measures.title")} description={t("measures.hint")}>
      {canManage && (
        <form className="mb-4 grid gap-3 sm:grid-cols-[1.4fr_1fr_0.8fr_1fr_auto] sm:items-end" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
          <Field label={t("measures.metric")}><Input value={metric} maxLength={60} placeholder={t("measures.metricPlaceholder")} onChange={(e) => setMetric(e.target.value)} /></Field>
          <Field label={t("measures.value")}><NumberInput value={value} onChange={setValue} /></Field>
          <Field label={t("measures.unit")}><Input value={unit} maxLength={20} onChange={(e) => setUnit(e.target.value)} /></Field>
          <Field label={t("date")}><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
          <Button type="submit" loading={add.isPending} disabled={!metric.trim() || !value.trim()}>{t("measures.add")}</Button>
        </form>
      )}
      <DataTable rows={q.data} loading={q.isLoading} error={q.error?.message} onRetry={() => void q.refetch()} rowKey={(m) => m.id} dense
        empty={{ title: t("measures.empty"), hint: t("measures.emptyHint") }}
        columns={[
          { header: t("date"), sortValue: (m) => m.taken_on, cell: (m) => formatDate(m.taken_on) },
          { header: t("measures.metric"), cell: (m) => <span className="font-medium">{m.metric}</span> },
          { header: t("measures.value"), align: "right", cell: (m) => `${Number(m.value)}${m.unit ? ` ${m.unit}` : ""}` },
          { header: t("note"), hideBelow: "sm", cell: (m) => m.note ?? "—" },
          { header: "", align: "right", cell: (m) => (canManage ? <IconButton label={t("measures.remove")} onClick={() => remove.mutate(m.id)}><Trash2 className="h-4 w-4" /></IconButton> : null) },
        ]} />
    </Card>
  );
}
