import { Plus } from "lucide-react";
import { useState } from "react";

import { Badge, Button, DataTable, money, PageHeader, useCan, useTranslation } from "@/sdk";

import { OfferForm } from "../components/OfferForm";
import { useBranch, useOffers } from "../hooks";
import type { Offer } from "../types";

export default function ServicesPage() {
  const { t } = useTranslation("bookings");
  const canSetup = useCan("bookings.setup");
  const { companyId, currency } = useBranch();
  const list = useOffers(companyId, false);
  const [editing, setEditing] = useState<Offer | "new" | null>(null);

  return (
    <>
      <PageHeader title={t("offers.title")} description={t("offers.hint")}
        actions={canSetup && <Button onClick={() => setEditing("new")}><Plus className="h-4 w-4" />{t("offers.new")}</Button>} />
      <DataTable
        rows={list.data} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()} rowKey={(o) => o.id}
        empty={{ title: t("offers.empty"), hint: t("offers.emptyHint"), action: canSetup ? <Button onClick={() => setEditing("new")}>{t("offers.new")}</Button> : undefined }}
        columns={[
          { header: t("offers.name"), sortValue: (o) => o.name, cell: (o) => (canSetup ? <button type="button" className="text-left font-medium hover:underline" onClick={() => setEditing(o)}>{o.name}</button> : <span className="font-medium">{o.name}</span>) },
          { header: t("offers.duration"), hideBelow: "sm", align: "right", cell: (o) => `${o.duration_minutes} ${t("minutes")}` },
          { header: t("offers.price"), align: "right", cell: (o) => (<span className="inline-flex items-center justify-end gap-2">{money(o.price, currency)}{o.price_is_example && <span title={t("offers.exampleHint")}><Badge tone="warn">{t("offers.example")}</Badge></span>}</span>) },
          { header: t("offers.type"), hideBelow: "md", cell: (o) => (o.kind === "class" ? t("offers.classOf", { count: o.capacity }) : t("offers.typeAppointment")) },
          { header: t("offers.people"), hideBelow: "lg", align: "right", cell: (o) => o.resource_ids.length },
          { header: t("offers.online"), hideBelow: "lg", cell: (o) => (o.kind === "class" ? "—" : o.show_publicly ? t("yes") : t("no")) },
          { header: t("status.label"), cell: (o) => <Badge tone={o.is_active ? "ok" : "neutral"}>{o.is_active ? t("resources.activeBadge") : t("resources.inactiveBadge")}</Badge> },
        ]}
      />
      <OfferForm open={editing !== null} onClose={() => setEditing(null)} offer={editing && editing !== "new" ? editing : undefined} />
    </>
  );
}
