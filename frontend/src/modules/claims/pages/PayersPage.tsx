import { Plus } from "lucide-react";
import { useState } from "react";

import { Badge, Button, type Column, DataTable, money, PageHeader, useCan, useTranslation } from "@/sdk";

import { PayerDrawer } from "../components/PayerDrawer";
import { SettingsCard } from "../components/SettingsCard";
import { useClaimSettings, useClaimsCompany, usePayers } from "../hooks";
import type { Payer } from "../types";

/** The payers (insurers, schemes, fleet owners, employers) with their terms as data, and the claim settings. */
export default function PayersPage() {
  const { t } = useTranslation("claims");
  const { companyId, currency, isLoading } = useClaimsCompany();
  const canEdit = useCan("claims.settings");
  const payers = usePayers(companyId);
  const settings = useClaimSettings(companyId);
  const [editing, setEditing] = useState<Payer | null>(null);
  const [creating, setCreating] = useState(false);
  const columns: Column<Payer>[] = [
    { header: t("payers.name"), sortValue: (p) => p.name, cell: (p) => <span><span className="font-medium">{p.name}</span><span className="block text-xs text-muted">{t(`payers.kinds.${p.kind}`)}{p.customer_name ? ` · ${p.customer_name}` : ""}</span></span> },
    { header: t("payers.terms"), hideBelow: "md", cell: (p) => (
      <span className="text-sm">
        {Object.entries(p.labour_rates).map(([k, v]) => `${k} ${money(String(v), currency)}`).join(", ") || "—"}
        <span className="block text-xs text-muted">{t("payers.partsLine", { discount: Number(p.parts_discount_pct), markup: Number(p.parts_markup_pct) })} · {t("payers.daysLine", { n: p.payment_days })}</span>
      </span>) },
    { header: t("payers.limit"), align: "right", hideBelow: "lg", cell: (p) => <span className="tnum">{p.approval_limit ? money(p.approval_limit, currency) : "—"}</span> },
    { header: t("payers.contacts"), hideBelow: "lg", cell: (p) => p.contacts.map((c) => String(c.name)).join(", ") || "—" },
    { header: "", cell: (p) => (p.is_active ? null : <Badge tone="neutral">{t("payers.inactive")}</Badge>) },
  ];
  return (
    <>
      <PageHeader title={t("payers.title")} description={t("payers.hint")} actions={canEdit && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("payers.new")}</Button>} />
      <div className="space-y-6">
        <DataTable rows={payers.data} columns={columns} rowKey={(p) => p.id} loading={isLoading || payers.isLoading} error={payers.error?.message ?? null} onRetry={() => void payers.refetch()}
          empty={{ title: t("payers.empty"), hint: t("payers.emptyHint"), action: canEdit ? <Button onClick={() => setCreating(true)}>{t("payers.new")}</Button> : undefined }} />
        {payers.data && payers.data.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {payers.data.map((p) => <Button key={p.id} size="sm" variant="secondary" onClick={() => setEditing(p)}>{canEdit ? t("payers.edit", { name: p.name }) : t("payers.view", { name: p.name })}</Button>)}
          </div>
        )}
        {settings.data && <SettingsCard settings={settings.data} canEdit={canEdit} />}
      </div>
      <PayerDrawer open={creating || editing !== null} payer={editing} companyId={companyId} onClose={() => { setCreating(false); setEditing(null); }} />
    </>
  );
}
