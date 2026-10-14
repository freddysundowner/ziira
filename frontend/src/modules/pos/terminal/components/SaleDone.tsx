import { CheckCircle2, Printer } from "lucide-react";

import { api, Alert, Button, ErrorState, money, SkeletonRows, unwrap, useQuery, useTranslation, type Schemas, humanise } from "@/sdk";

import { Receipt } from "./Receipt";
import { Row } from "./Receipt";

/** The sale went through: change to give, the receipt to print, and a new sale one key away. */
export function SaleDone({ sale, currency, onNewSale }: { sale: Schemas["SaleOut"]; currency: string; onNewSale: () => void }) {
  const { t } = useTranslation("pos");
  const receipt = useQuery({
    queryKey: ["pos-terminal", "receipt", sale.id],
    queryFn: () => unwrap(api.GET("/api/v1/pos/sales/{sale_id}/receipt", { params: { path: { sale_id: sale.id }, query: { format: "json" } } })),
  });
  const change = Number(sale.change);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:flex-row">
      <div className="no-print flex flex-1 flex-col items-center justify-center gap-4 p-6 text-center">
        <CheckCircle2 className="h-14 w-14 text-ok" />
        <div>
          <h1 className="text-2xl font-bold">{t("terminal.done.title")}</h1>
          <p className="text-sm text-muted">{sale.number}</p>
        </div>
        <p className="tnum text-4xl font-bold">{money(sale.total, currency)}</p>
        {change > 0 && (
          <div className="rounded-xl bg-ok-soft px-6 py-3 text-ok">
            <p className="text-xs font-medium uppercase tracking-wide">{t("terminal.done.change")}</p>
            <p className="tnum text-3xl font-bold">{money(sale.change, currency)}</p>
          </div>
        )}
        <div className="w-full max-w-xs space-y-1 text-sm">
          {sale.payments.map((p) => <Row key={p.id} left={<span className="text-muted">{humanise(p.method)}{p.external_ref ? ` · ${p.external_ref}` : ""}</span>} right={money(p.amount, currency)} />)}
        </div>
        {sale.warnings.length > 0 && <Alert tone="warn" className="max-w-sm text-left">{sale.warnings.map((w) => humanise(w)).join(" · ")}</Alert>}
        <div className="flex w-full max-w-xs flex-col gap-2">
          <Button size="lg" onClick={onNewSale} autoFocus className="h-14 text-lg">{t("terminal.done.newSale")}</Button>
          <Button size="lg" variant="secondary" onClick={() => window.print()} disabled={!receipt.data}><Printer className="h-4 w-4" />{t("terminal.done.print")}</Button>
        </div>
      </div>
      <div className="flex-1 bg-sunken p-4 lg:overflow-y-auto">
        {receipt.isLoading ? <SkeletonRows rows={8} cols={1} />
          : receipt.error ? <ErrorState title={t("terminal.done.receiptFailed")} message={receipt.error.message} onRetry={() => void receipt.refetch()} />
          : receipt.data && <Receipt doc={receipt.data} currency={currency} />}
      </div>
    </div>
  );
}
