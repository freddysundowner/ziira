import { useEffect, useState } from "react";

import { api, Button, Drawer, Field, FormGrid, Input, Select, Textarea, toast, today, unwrap, useMutation, useTranslation } from "@/sdk";

import { useOffers, useRefreshBookings } from "../hooks";

/** Put someone on the waitlist for a service between two dates. */
export function WaitlistForm({ open, onClose, branchId, companyId, offerId, day }: { open: boolean; onClose: () => void; branchId: string; companyId: string; offerId?: string; day?: string }) {
  const { t } = useTranslation("bookings");
  const offers = useOffers(companyId);
  const refresh = useRefreshBookings();
  const [offer, setOffer] = useState("");
  const [from, setFrom] = useState(today());
  const [to, setTo] = useState(today());
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    if (!open) return;
    setOffer(offerId ?? ""); setFrom(day ?? today()); setTo(day ?? today()); setName(""); setPhone(""); setEmail(""); setNote("");
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/waitlist", { body: {
      offer_id: offer, branch_id: branchId, wanted_from: from, wanted_to: to < from ? from : to, client_name: name.trim(),
      client_phone: phone.trim() || null, client_email: email.trim() || null, note: note.trim() || null } })),
    onSuccess: () => { void refresh(); toast(t("waitlist.added"), "ok"); onClose(); },
  });

  return (
    <Drawer open={open} onClose={onClose} title={t("waitlist.add")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("close")}</Button><Button type="submit" form="waitlist-form" loading={save.isPending} disabled={!offer || !name.trim()}>{t("waitlist.add")}</Button></>}>
      <form id="waitlist-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <Field label={t("form.service")} required>
          <Select value={offer} onChange={(e) => setOffer(e.target.value)} autoFocus>
            <option value="">{t("form.pickService")}</option>
            {(offers.data ?? []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </Select>
        </Field>
        <FormGrid>
          <Field label={t("waitlist.from")}><Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label={t("waitlist.to")}><Input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></Field>
        </FormGrid>
        <Field label={t("form.name")} required><Input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} /></Field>
        <FormGrid>
          <Field label={t("form.phone")}><Input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={30} /></Field>
          <Field label={t("form.email")}><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={200} /></Field>
        </FormGrid>
        <Field label={t("form.note")}><Textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} /></Field>
      </form>
    </Drawer>
  );
}
