import { UserPlus } from "lucide-react";
import { useCallback, useState } from "react";

import { api, Button, Combobox, Field, Input, Modal, toast, unwrap, useMutation, useTranslation } from "@/sdk";

/** Find a client by name or phone (two letters are enough), or add a new one. */
export function ClientPicker({ companyId, value, label, onChange, allowAdd = true, placeholder, disabled }: {
  companyId: string; value: string; label?: string | null; onChange: (id: string, label: string) => void; allowAdd?: boolean; placeholder?: string; disabled?: boolean;
}) {
  const { t } = useTranslation("bookings");
  const [adding, setAdding] = useState(false);
  const search = useCallback(async (text: string) => {
    if (text.trim().length < 2) return [];
    const rows = await unwrap(api.GET("/api/v1/bookings/clients/search", { params: { query: { company_id: companyId, q: text.trim() } } }));
    return rows.map((c) => ({ value: c.id, label: c.name, hint: c.sku }));
  }, [companyId]);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="min-w-0 flex-1 basis-56">
        <Combobox value={value} selectedLabel={label ?? undefined} search={search} disabled={disabled} placeholder={placeholder ?? t("checkout.clientSearch")}
          onChange={(id, option) => onChange(id, option?.label ?? "")} />
      </div>
      {allowAdd && !disabled && <Button variant="secondary" onClick={() => setAdding(true)}><UserPlus className="h-4 w-4" />{t("checkout.addClient")}</Button>}
      <AddClient open={adding} onClose={() => setAdding(false)} companyId={companyId} onAdded={(id, name) => { onChange(id, name); setAdding(false); }} />
    </div>
  );
}

function AddClient({ open, onClose, companyId, onAdded }: { open: boolean; onClose: () => void; companyId: string; onAdded: (id: string, name: string) => void }) {
  const { t } = useTranslation("bookings");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const add = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/clients", { params: { query: { company_id: companyId, name: name.trim(), phone: phone.trim() || undefined } } })),
    onSuccess: (c) => { toast(t("checkout.clientAdded", { name: c.name }), "ok"); setName(""); setPhone(""); onAdded(c.id, c.name); },
  });
  return (
    <Modal open={open} onClose={onClose} title={t("checkout.addClient")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("checkout.close")}</Button><Button type="submit" form="add-client" loading={add.isPending} disabled={!name.trim()}>{t("checkout.save")}</Button></>}>
      <form id="add-client" className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (name.trim() && !add.isPending) add.mutate(); }}>
        <Field label={t("checkout.clientName")} required><Input value={name} maxLength={200} autoFocus onChange={(e) => setName(e.target.value)} /></Field>
        <Field label={t("checkout.clientPhone")} hint={t("checkout.clientPhoneHint")}><Input type="tel" value={phone} maxLength={30} onChange={(e) => setPhone(e.target.value)} /></Field>
      </form>
    </Modal>
  );
}
