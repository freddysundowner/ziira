import { useState } from "react";

import { Alert, api, ConfirmDialog, money, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { ADDONS_KEY, type Invoice } from "../billing/lib";
import type { UnitCard } from "./lib";

/**
 * Asks once, in plain words, before an add-on is bought. Saying yes makes the invoice (one line, ready to pay) and hands it
 * to the same payment steps as Plan & billing. Nothing is switched on here: only a confirmed payment does that.
 */
export function BuyDialog({ unit, onInvoice, onClose }: { unit: UnitCard; onInvoice: (invoice: Invoice) => void; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [failure, setFailure] = useState<string | null>(null);
  const price = money(unit.sale_price, (unit.sale_currency ?? "").trim() || undefined);
  const buy = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/billing/addons/{unit}/buy", { params: { path: { unit: unit.name } } })),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ADDONS_KEY });
      void qc.invalidateQueries({ queryKey: ["billing-invoices"] });
      if (r.invoice) onInvoice(r.invoice);
    },
    onError: (e: Error) => setFailure(e.message),
  });
  return (
    <ConfirmDialog open onClose={onClose} busy={buy.isPending} title={t("apps.sale.confirmTitle", { name: unit.title })} confirmLabel={t("apps.sale.continue")}
      onConfirm={() => { setFailure(null); buy.mutate(); }}
      message={<div className="space-y-3"><p>{t("apps.sale.confirmAsk", { name: unit.title, price })}</p>{unit.sale_tax_inclusive && <p className="text-xs text-muted">{t("apps.sale.taxIncl")}</p>}{failure && <Alert tone="bad">{failure}</Alert>}</div>} />
  );
}
