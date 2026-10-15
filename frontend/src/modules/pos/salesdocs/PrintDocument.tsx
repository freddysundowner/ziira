import { Printer } from "lucide-react";

import { api, Button, ErrorState, Modal, Skeleton, unwrap, useCompany, useQuery, useTranslation } from "@/sdk";

import { PrintArea } from "../components/PrintArea";
import { ReceiptSheet } from "../components/Receipt";

/** An invoice or a customer payment receipt as the backend lays it out, with a Print button. Opening it here is always a reprint. */
export function PrintDocument({ kind, id, companyId, open, onClose }: { kind: "invoice" | "receipt"; id: string; companyId: string; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("pos");
  const currency = useCompany(companyId).company?.currency;
  const doc = useQuery({
    enabled: open, queryKey: ["pos-print", kind, id],
    queryFn: () => unwrap(kind === "invoice"
      ? api.GET("/api/v1/pos/invoices/{invoice_id}/print", { params: { path: { invoice_id: id }, query: { format: "json", copy: true } } })
      : api.GET("/api/v1/pos/receipts/{receipt_id}/print", { params: { path: { receipt_id: id }, query: { format: "json", copy: true } } })),
  });
  return (
    <Modal open={open} onClose={onClose} title={t(kind === "invoice" ? "docs.printInvoice" : "docs.printReceipt")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("close")}</Button><Button disabled={!doc.data} onClick={() => window.print()}><Printer className="h-4 w-4" />{t("print")}</Button></>}>
      {doc.error ? <ErrorState message={doc.error.message} onRetry={() => void doc.refetch()} />
        : !doc.data ? <Skeleton className="h-64 w-full" />
        : (
          <>
            <div className="rounded-lg border border-line bg-surface p-4"><ReceiptSheet doc={doc.data} currency={currency} /></div>
            {open && <PrintArea><ReceiptSheet doc={doc.data} currency={currency} /></PrintArea>}
          </>
        )}
    </Modal>
  );
}
