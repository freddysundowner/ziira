import { Printer } from "lucide-react";

import { api, Button, Card, DataTable, formatDate, money, Stat, unwrap, useCurrency, useQuery, useTranslation } from "@/sdk";

import { AGE_BUCKETS, amountDue } from "../lib";
import { Status } from "./Status";

interface Row { id: string; date: string; kind: "bill" | "credit" | "refund"; number: string; ref: string; amount: string; due?: string; status?: string; href?: string }

/** The supplier's account as we keep it: bills, credit notes and refunds, with what is owed now and how late it is. */
export function SupplierStatementTab({ supplierId, companyId }: { supplierId: string; companyId: string }) {
  const { t } = useTranslation("purchasing");
  const currency = useCurrency(companyId);
  const owed = useQuery({ queryKey: ["purchasing", "payables", supplierId], queryFn: () => unwrap(api.GET("/api/v1/purchasing/payables", { params: { query: { supplier_id: supplierId } } })) });
  const rows = useQuery({
    queryKey: ["purchasing", "statement", supplierId],
    queryFn: async (): Promise<Row[]> => {
      const query = { supplier_id: supplierId, limit: 100 };
      const [bills, credits, refunds] = await Promise.all([
        unwrap(api.GET("/api/v1/purchasing/bills", { params: { query } })),
        unwrap(api.GET("/api/v1/purchasing/credit-notes", { params: { query } })),
        unwrap(api.GET("/api/v1/purchasing/refunds", { params: { query } })),
      ]);
      return [
        ...bills.filter((b) => !["draft", "cancelled"].includes(b.status)).map((b): Row => ({ id: b.id, date: b.bill_date, kind: "bill", number: b.number, ref: b.supplier_invoice_no, amount: b.total, due: amountDue(b), status: b.status, href: `/bills/${b.id}` })),
        ...credits.map((c): Row => ({ id: c.id, date: c.credit_date, kind: "credit", number: c.number, ref: c.supplier_credit_no, amount: c.total, href: `/credit-notes/${c.id}` })),
        ...refunds.map((r): Row => ({ id: r.id, date: r.received_on, kind: "refund", number: r.number, ref: r.reference ?? "", amount: r.amount, status: r.status, href: "/refunds" })),
      ].sort((a, b) => b.date.localeCompare(a.date));
    },
  });
  const total = owed.data?.total;
  const buckets = owed.data?.buckets ?? {};

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label={t("balanceOwed")} value={money(total, currency)} loading={owed.isLoading} tone={Number(total) > 0 ? "bad" : undefined} />
        {AGE_BUCKETS.map((b) => <Stat key={b} label={t(`ageing.${b}`)} value={money(buckets[b], currency)} loading={owed.isLoading} />)}
      </div>
      {owed.error && <p className="text-sm text-bad">{owed.error.message}</p>}
      <Card title={t("statement")} description={t("statementHint")} flush actions={<Button size="sm" variant="secondary" onClick={() => window.print()}><Printer className="h-4 w-4" />{t("print")}</Button>}>
        <DataTable rows={rows.data} loading={rows.isLoading} error={rows.error?.message} onRetry={() => void rows.refetch()} rowKey={(r) => `${r.kind}${r.id}`}
          rowHref={(r) => r.href ?? "/refunds"} empty={{ title: t("noStatement") }}
          columns={[
            { header: t("date"), sortValue: (r) => r.date, cell: (r) => formatDate(r.date) },
            { header: t("type"), cell: (r) => t(`docKind.${r.kind}`) },
            { header: t("number"), cell: (r) => <span className="font-mono text-xs">{r.number}</span> },
            { header: t("theirRef"), hideBelow: "sm", cell: (r) => r.ref || "—" },
            { header: t("amount"), align: "right", cell: (r) => (r.kind === "bill" ? money(r.amount, currency) : `− ${money(r.amount, currency)}`) },
            { header: t("stillOwed"), hideBelow: "md", align: "right", cell: (r) => (r.due !== undefined ? money(r.due, currency) : "") },
            { header: t("status"), hideBelow: "sm", cell: (r) => (r.status ? <Status status={r.status} /> : "") },
          ]} />
        <p className="border-t border-line px-4 py-2 text-xs text-muted">{t("statementLimit")}</p>
      </Card>
    </div>
  );
}
