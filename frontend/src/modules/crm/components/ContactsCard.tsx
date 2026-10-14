import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import {
  api, Button, Card, ConfirmDialog, DataTable, Drawer, Field, FormGrid, IconButton, Input, orNull, toast, unwrap, useCan, useFormState, useMutation,
  useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { usePhoneHint } from "./PhoneHint";

/** The people at a customer, with a form to add one and a confirmed remove. */
export function ContactsCard({ customerId, companyId }: { customerId: string; companyId: string }) {
  const { t } = useTranslation("crm");
  const qc = useQueryClient();
  const canManage = useCan("customers.manage");
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<{ id: string; name: string } | null>(null);
  const key = ["customer-contacts", customerId];
  const contacts = useQuery({ queryKey: key, queryFn: () => unwrap(api.GET("/api/v1/crm/customers/{customer_id}/contacts", { params: { path: { customer_id: customerId } } })) });
  const f = useFormState({ name: "", role: "", phone: "", email: "" });
  const phoneHint = usePhoneHint(companyId);

  const add = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/crm/customers/{customer_id}/contacts", { params: { path: { customer_id: customerId } }, body: {
      name: f.values.name.trim(), role: orNull(f.values.role), phone: orNull(f.values.phone), email: orNull(f.values.email) } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: key }); toast(t("contactAdded"), "ok"); f.reset(); setAdding(false); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const remove = useMutation({
    mutationFn: (contactId: string) => unwrap(api.DELETE("/api/v1/crm/customers/{customer_id}/contacts/{contact_id}", { params: { path: { customer_id: customerId, contact_id: contactId } } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: key }); toast(t("contactRemoved"), "ok"); setRemoving(null); },
  });

  return (
    <Card title={t("contacts")} flush actions={canManage && <Button size="sm" variant="secondary" onClick={() => setAdding(true)}><Plus className="h-3.5 w-3.5" />{t("addContact")}</Button>}>
      <DataTable
        rows={contacts.data} loading={contacts.isLoading} error={contacts.error?.message} onRetry={() => void contacts.refetch()} rowKey={(c) => c.id}
        empty={{ title: t("noContacts"), hint: t("contactsHint") }}
        columns={[
          { header: t("name"), cell: (c) => <span className="font-medium">{c.name}</span> },
          { header: t("role"), hideBelow: "sm", cell: (c) => c.role ?? "—" },
          { header: t("phone"), cell: (c) => c.phone ?? "—" },
          { header: t("email"), hideBelow: "md", cell: (c) => c.email ?? "—" },
          { header: "", align: "right", cell: (c) => canManage && <IconButton label={t("removeContact")} onClick={() => setRemoving({ id: c.id, name: c.name })}><Trash2 className="h-4 w-4" /></IconButton> },
        ]}
      />
      <Drawer open={adding} onClose={() => setAdding(false)} title={t("addContact")}
        footer={<><Button variant="secondary" onClick={() => setAdding(false)}>{t("cancel")}</Button><Button type="submit" form="contact-form" loading={add.isPending}>{t("save")}</Button></>}>
        <form id="contact-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
          <Field label={t("name")} required error={f.error("name")}><Input {...f.bind("name")} required autoFocus /></Field>
          <Field label={t("role")} hint={t("roleHint")} error={f.error("role")}><Input {...f.bind("role")} /></Field>
          <FormGrid>
            <Field label={t("phone")} hint={phoneHint} error={f.error("phone")}><Input type="tel" {...f.bind("phone")} /></Field>
            <Field label={t("email")} error={f.error("email")}><Input type="email" {...f.bind("email")} /></Field>
          </FormGrid>
        </form>
      </Drawer>
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} danger busy={remove.isPending} title={t("removeContact")} confirmLabel={t("remove")}
        message={t("removeContactAsk", { name: removing?.name })} onConfirm={() => removing && remove.mutate(removing.id)} />
    </Card>
  );
}
