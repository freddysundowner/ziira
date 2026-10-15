import { X } from "lucide-react";
import { useCallback, useRef } from "react";

import { api, Combobox, unwrap, useTranslation } from "@/sdk";

import type { CachedCustomer } from "../offline/cache";

/** Attach a customer to the sale (optional): looked up on the server as the cashier types. Needed for credit sales. */
export function CustomerPicker({ customerId, customerName, online, saved, onChange }: {
  customerId: string; customerName: string; online: boolean; saved: CachedCustomer[];
  onChange: (id: string, name: string, phone: string) => void;
}) {
  const { t } = useTranslation("pos");
  const phones = useRef(new Map<string, string>());
  const search = useCallback(async (text: string) => {
    // Without a connection, the customers kept on this device are searched.
    if (!online) {
      const q = text.trim().toLowerCase();
      const found = saved.filter((c) => !q || c.name.toLowerCase().includes(q) || c.code.toLowerCase().includes(q) || (c.phone ?? "").includes(q)).slice(0, 20);
      for (const c of found) phones.current.set(c.id, c.phone ?? "");
      return found.map((c) => ({ value: c.id, label: c.name, hint: [c.code, c.phone].filter(Boolean).join(" · ") }));
    }
    const rows = await unwrap(api.GET("/api/v1/crm/customers", { params: { query: { search: text || undefined, status: "active", limit: 20 } } }));
    for (const c of rows) phones.current.set(c.id, c.phone ?? "");
    return rows.map((c) => ({ value: c.id, label: c.name, hint: [c.code, c.phone].filter(Boolean).join(" · ") }));
  }, [online, saved]);

  return (
    <div className="flex items-center gap-1.5">
      <div className="min-w-0 flex-1">
        <Combobox value={customerId} selectedLabel={customerName} placeholder={t("terminal.customer.walkIn")} search={search}
          onChange={(id, option) => onChange(id, option?.label ?? "", phones.current.get(id) ?? "")} />
      </div>
      {customerId && (
        <button type="button" aria-label={t("terminal.customer.remove")} title={t("terminal.customer.remove")} onClick={() => onChange("", "", "")}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-sunken hover:text-ink"><X className="h-4 w-4" /></button>
      )}
    </div>
  );
}
