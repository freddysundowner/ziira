import { useState } from "react";

import { api, Badge, Button, Card, DataTable, formatDate, money, toast, unwrap, useQuery, useTranslation } from "@/sdk";

import { ADDONS_KEY, type Invoice } from "./lib";
import { openPrintable } from "./InvoicesCard";
import { PayDialog } from "./PayDialog";

/** The add-ons this business bought (one payment each) with their receipts; one still waiting at the checkout can be paid from here. */
export function AddonsCard() {
  const { t } = useTranslation("kernel");
  const shop = useQuery({ queryKey: ADDONS_KEY, queryFn: () => unwrap(api.GET("/api/v1/billing/addons")) });
  const [paying, setPaying] = useState<string | null>(null);
  const invoices = useQuery({ queryKey: ["billing-invoices"], queryFn: () => unwrap(api.GET("/api/v1/billing/invoices")) });
  const rows = (shop.data?.purchases ?? []).filter((p) => p.status === "active" || p.status === "pending");
  if (shop.isLoading || rows.length === 0) return null;
  const invoice: Invoice | undefined = invoices.data?.find((i) => i.id === paying);
  const receipt = (id: string) => openPrintable(id).catch((e: unknown) => toast(e instanceof Error && e.message !== "blocked" ? e.message : t("billing.popupBlocked"), "bad"));
  return (
    <Card title={t("billing.addonsTitle")} description={t("billing.addonsHint")} flush>
      <DataTable rows={rows} rowKey={(p) => p.id} pageSize={10} empty={{ title: t("billing.addonsNone") }}
        columns={[
          { header: t("billing.addonName"), cell: (p) => <span className="font-medium">{p.title}</span> },
          { header: t("billing.addonWhen"), hideBelow: "sm", cell: (p) => (p.purchased_at ? formatDate(p.purchased_at) : "—") },
          { header: t("billing.addonPaid"), align: "right", cell: (p) => (p.status === "pending" ? <Badge tone="warn">{t("billing.addonWaiting")}</Badge> : p.granted_by === "operator" ? <Badge tone="brand">{t("billing.addonGiven")}</Badge> : money(p.price, (p.currency ?? "").trim() || undefined)) },
          { header: "", align: "right", cell: (p) => p.status === "pending" && p.invoice_id
            ? <Button size="sm" onClick={() => setPaying(p.invoice_id)}>{t("billing.addonPay")}</Button>
            : p.invoice_id ? <Button size="sm" variant="ghost" onClick={() => void receipt(p.invoice_id as string)}>{t("apps.sale.receipt")}</Button> : null },
        ]} />
      {paying && invoice && <PayDialog invoice={invoice} onClose={() => setPaying(null)} />}
    </Card>
  );
}
