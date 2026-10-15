import { CheckCircle2, CloudOff, Printer } from "lucide-react";

import { api, Alert, Button, ErrorState, money, SkeletonRows, unwrap, useQuery, useTranslation, type Schemas, humanise } from "@/sdk";

import type { OutboxEntry } from "../offline/types";
import { Receipt } from "./Receipt";
import { Row } from "./Receipt";

/** The sale is recorded at the server (`sent`), or kept on this device to be sent when there is a connection (`saved`). */
export type DoneView = { kind: "sent"; sale: Schemas["SaleOut"] } | { kind: "saved"; entry: OutboxEntry; change: string };

/** The sale went through: change to give, the receipt to print, and a new sale one key away. */
export function SaleDone({ view, currency, onNewSale }: { view: DoneView; currency: string; onNewSale: () => void }) {
  const { t } = useTranslation("pos");
  const sent = view.kind === "sent" ? view.sale : null;
  const receipt = useQuery({
    enabled: !!sent,
    queryKey: ["pos-terminal", "receipt", sent?.id],
    queryFn: () => unwrap(api.GET("/api/v1/pos/sales/{sale_id}/receipt", { params: { path: { sale_id: sent!.id }, query: { format: "json" } } })),
  });
  const doc = view.kind === "saved" ? view.entry.receipt : receipt.data;
  const number = view.kind === "saved" ? view.entry.number : sent!.number;
  const total = view.kind === "saved" ? view.entry.total : sent!.total;
  const change = Number(view.kind === "saved" ? view.change : sent!.change);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:flex-row">
      <div className="no-print flex flex-1 flex-col items-center justify-center gap-4 p-6 text-center">
        {view.kind === "saved" ? <CloudOff className="h-14 w-14 text-warn" /> : <CheckCircle2 className="h-14 w-14 text-ok" />}
        <div>
          <h1 className="text-2xl font-bold">{view.kind === "saved" ? t("terminal.sync.savedTitle") : t("terminal.done.title")}</h1>
          <p className="text-sm text-muted" data-testid="sale-number">{number}</p>
        </div>
        <p className="tnum text-4xl font-bold">{money(total, currency)}</p>
        {view.kind === "saved" && <Alert tone="warn" className="max-w-sm text-left">{t("terminal.sync.savedHint")}</Alert>}
        {change > 0 && (
          <div className="rounded-xl bg-ok-soft px-6 py-3 text-ok">
            <p className="text-xs font-medium uppercase tracking-wide">{t("terminal.done.change")}</p>
            <p className="tnum text-3xl font-bold">{money(view.kind === "saved" ? view.change : sent!.change, currency)}</p>
          </div>
        )}
        <div className="w-full max-w-xs space-y-1 text-sm">
          {view.kind === "saved"
            ? view.entry.receipt.payments.map((p, i) => <Row key={i} left={<span className="text-muted">{humanise(p.label.toLowerCase())}</span>} right={money(p.amount, currency)} />)
            : sent!.payments.map((p) => <Row key={p.id} left={<span className="text-muted">{humanise(p.method)}{p.external_ref ? ` · ${p.external_ref}` : ""}</span>} right={money(p.amount, currency)} />)}
        </div>
        {sent && sent.warnings.length > 0 && <Alert tone="warn" className="max-w-sm text-left">{sent.warnings.map((w) => humanise(w)).join(" · ")}</Alert>}
        <div className="flex w-full max-w-xs flex-col gap-2">
          <Button size="lg" onClick={onNewSale} autoFocus className="h-14 text-lg">{t("terminal.done.newSale")}</Button>
          <Button size="lg" variant="secondary" onClick={() => window.print()} disabled={!doc}><Printer className="h-4 w-4" />{t("terminal.done.print")}</Button>
        </div>
      </div>
      <div className="flex-1 bg-sunken p-4 lg:overflow-y-auto">
        {view.kind === "sent" && receipt.isLoading ? <SkeletonRows rows={8} cols={1} />
          : view.kind === "sent" && receipt.error ? <ErrorState title={t("terminal.done.receiptFailed")} message={receipt.error.message} onRetry={() => void receipt.refetch()} />
          : doc && <Receipt doc={doc} currency={currency} />}
      </div>
    </div>
  );
}
