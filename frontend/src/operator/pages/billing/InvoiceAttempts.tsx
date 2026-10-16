import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge, formatDate, money, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { ATTEMPT_TONES } from "../../helpers/gateway";
import { AttemptDrawer } from "./AttemptsTab";

/** The tries to pay this invoice by itself; nothing is shown when there were none. */
export function InvoiceAttempts({ invoiceId }: { invoiceId: string }) {
  const { t } = useTranslation("operator");
  const [open, setOpen] = useState<string | null>(null);
  const list = useQuery({ queryKey: ["operator", "invoice-attempts", invoiceId], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/invoices/{invoice_id}/payment-attempts", { params: { path: { invoice_id: invoiceId } } })) });
  if (!list.data || list.data.length === 0) return null;
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold">{t("billing.attempts.onInvoice")}</h3>
      <ul className="divide-y divide-line rounded-lg border border-line">
        {list.data.map((a) => (
          <li key={a.id}>
            <button type="button" className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-sunken" onClick={() => setOpen(a.id)}>
              <span>{a.provider_label} · {formatDate(a.created_at, true)}</span>
              <span className="flex items-center gap-2">{money(a.amount, a.currency)}<Badge tone={ATTEMPT_TONES[a.status] ?? "neutral"}>{t(`billing.attempts.statuses.${a.status}`, a.status)}</Badge></span>
            </button>
          </li>
        ))}
      </ul>
      {open && <AttemptDrawer id={open} onClose={() => setOpen(null)} />}
    </section>
  );
}
