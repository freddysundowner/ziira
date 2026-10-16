import { Printer } from "lucide-react";
import { useState } from "react";

import { api, Badge, Button, Card, DataTable, formatDate, money, toast, unwrap, useQuery, useTranslation } from "@/sdk";

import { invoiceTone, isOwed, type Invoice } from "./lib";
import { PayDialog } from "./PayDialog";

/** The printable page needs the bearer token, so it is fetched by the API client and opened as a local page the owner can print or save as PDF. */
async function openPrintable(id: string): Promise<void> {
  const win = window.open("", "_blank");
  try {
    const html = await unwrap(api.GET("/api/v1/billing/invoices/{invoice_id}/html", { params: { path: { invoice_id: id } }, parseAs: "text" }));
    const url = URL.createObjectURL(new Blob([html as unknown as string], { type: "text/html" }));
    if (!win) throw new Error("blocked");
    win.opener = null;
    win.location.href = url;
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (e) {
    win?.close();
    throw e;
  }
}

export function InvoicesCard() {
  const { t } = useTranslation("kernel");
  const [busy, setBusy] = useState<string | null>(null);
  const [paying, setPaying] = useState<Invoice | null>(null);
  const invoices = useQuery({ queryKey: ["billing-invoices"], queryFn: () => unwrap(api.GET("/api/v1/billing/invoices")) });
  const print = (i: Invoice) => {
    setBusy(i.id);
    openPrintable(i.id).catch((e: unknown) => toast(e instanceof Error && e.message !== "blocked" ? e.message : t("billing.popupBlocked"), "bad")).finally(() => setBusy(null));
  };
  return (
    <Card title={t("billing.invoicesTitle")} flush>
      <DataTable
        rows={invoices.data} loading={invoices.isLoading} error={invoices.error?.message} onRetry={() => void invoices.refetch()} rowKey={(i) => i.id} pageSize={10}
        empty={{ title: t("billing.noInvoices"), hint: t("billing.noInvoicesHint") }}
        columns={[
          { header: t("billing.invNumber"), cell: (i) => <span className="font-medium">{i.number ?? "—"}</span> },
          { header: t("billing.invIssued"), hideBelow: "md", sortValue: (i) => i.issue_date ?? "", cell: (i) => formatDate(i.issue_date) },
          { header: t("billing.invDue"), hideBelow: "sm", cell: (i) => formatDate(i.due_date) },
          { header: t("billing.invTotal"), align: "right", hideBelow: "sm", cell: (i) => money(i.total, i.currency.trim()) },
          { header: t("billing.invBalance"), align: "right", cell: (i) => <span className={isOwed(i) ? "font-semibold text-bad" : ""}>{money(i.balance, i.currency.trim())}</span> },
          { header: t("status"), cell: (i) => <Badge tone={invoiceTone(i.status)}>{t(`billing.invStatus.${i.status}`, { defaultValue: i.status })}</Badge> },
          { header: "", align: "right", cell: (i) => (
            <div className="flex justify-end gap-1">
            {isOwed(i) && <Button size="sm" onClick={() => setPaying(i)}>{t("billing.pay.button")}</Button>}
            <Button size="sm" variant="ghost" loading={busy === i.id} onClick={() => print(i)} aria-label={t("billing.printInvoice", { number: i.number ?? "" })}>
              <Printer className="h-4 w-4" /><span className="hidden sm:inline">{i.status === "paid" ? t("billing.receipt") : t("billing.print")}</span>
            </Button>
            </div>
          ) },
        ]}
      />
      {paying && <PayDialog invoice={paying} onClose={() => setPaying(null)} />}
    </Card>
  );
}
