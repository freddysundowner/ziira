import { Button, Field, FormGrid, Input, useTranslation } from "@/sdk";

import { useUnit } from "../hooks";
import type { ReceiveForm } from "../receive";
import { CustomerPicker } from "./pickers";

/** Who brought the item: a customer from the list (when Customers is on), or just a name and a phone number. */
export function ReceiveCustomer({ form, update }: { form: ReceiveForm; update: (patch: Partial<ReceiveForm>) => void }) {
  const { t } = useTranslation("jobs");
  const hasCustomers = useUnit("crm");
  return (
    <div className="space-y-4">
      {hasCustomers && (
        <Field label={t("receive.customer")} hint={form.customerId ? undefined : t("receive.customerHint")}>
          <CustomerPicker value={form.customerId} onChange={(id) => update({ customerId: id })} />
        </Field>
      )}
      {!form.customerId && (
        <>
        <FormGrid>
          <Field label={t("receive.customerName")}><Input className="h-11" autoComplete="off" maxLength={160} value={form.customerName} onChange={(e) => update({ customerName: e.target.value })} /></Field>
          <Field label={t("receive.customerPhone")}><Input className="h-11" type="tel" autoComplete="off" maxLength={40} value={form.customerPhone} onChange={(e) => update({ customerPhone: e.target.value })} /></Field>
        </FormGrid>
        {!form.customerName.trim() && <Button size="sm" variant="secondary" onClick={() => update({ customerName: t("garage.receive.walkInName") })}>{t("garage.receive.walkIn")}</Button>}
        <p className="text-xs text-muted">{t("garage.receive.walkInHint")}</p>
        </>
      )}
    </div>
  );
}
