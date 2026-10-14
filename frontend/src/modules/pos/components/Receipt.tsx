import { Printer } from "lucide-react";

import { api, Button, ErrorState, Modal, money, Schemas, Skeleton, unwrap, useCompany, useQuery, useTranslation } from "@/sdk";

import { PrintArea, Row, Rule, Sheet } from "./PrintArea";

type Doc = Schemas["PrintOut"];

/** A receipt as the backend lays it out (company header, lines, VAT by rate, totals, payments, footer). */
export function ReceiptSheet({ doc, currency }: { doc: Doc; currency?: string }) {
  const { t } = useTranslation("pos");
  const m = (v: string) => money(v, currency);
  return (
    <Sheet>
      {doc.header.map((h, i) => <p key={i} className={i === 0 ? "text-center text-sm font-bold" : "text-center"}>{h}</p>)}
      <Rule />
      <p className="text-center font-bold uppercase">{doc.title} {doc.number}{doc.is_copy && ` · ${t("copy")}`}</p>
      {doc.meta.map(([label, value]) => <Row key={label} left={label} right={value} />)}
      <Rule />
      {doc.lines.map((l, i) => (
        <div key={i} className="mb-1">
          <p>{l.description}</p>
          <Row left={`  ${Number(l.quantity)} x ${m(l.unit_price)}`} right={m(l.amount)} />
        </div>
      ))}
      <Rule />
      {doc.totals.map((x) => <Row key={x.label} left={x.label} right={m(x.amount)} strong={/total/i.test(x.label)} />)}
      <Rule />
      {doc.payments.map((x) => <Row key={x.label} left={x.label} right={m(x.amount)} />)}
      {doc.vat.length > 0 && (
        <>
          <Rule />
          <p className="font-bold">{t("vatBreakdown")}</p>
          {doc.vat.map((v) => <Row key={v.rate} left={`${Number(v.rate)}%  ${m(v.net)}`} right={m(v.tax)} />)}
        </>
      )}
      {doc.notes.map((n) => <p key={n} className="mt-2 text-center font-bold">{n}</p>)}
      {doc.footer.length > 0 && <Rule />}
      {doc.footer.map((f, i) => <p key={i} className="text-center">{f}</p>)}
    </Sheet>
  );
}

/** A sale's receipt on screen, with a Print button. Opening it from here is always a reprint, so it is marked as a copy. */
export function ReceiptModal({ saleId, companyId, open, onClose }: { saleId: string; companyId: string; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("pos");
  const currency = useCompany(companyId).company?.currency;
  const doc = useQuery({
    enabled: open, queryKey: ["pos-receipt", saleId, "copy"],
    queryFn: () => unwrap(api.GET("/api/v1/pos/sales/{sale_id}/receipt", { params: { path: { sale_id: saleId }, query: { format: "json", copy: true } } })),
  });
  return (
    <Modal open={open} onClose={onClose} title={t("receipt")}
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
