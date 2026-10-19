import { UserPlus } from "lucide-react";
import { useState } from "react";

import { api, Button, Card, DataTable, Field, formatDate, Input, Modal, toast, unwrap, useCan, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

import type { Member } from "../hooks";

/** Guest passes: how many are left this period, who was brought, and a button to bring a guest. */
export function GuestsCard({ member }: { member: Member }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const canManage = useCan("memberships.manage");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const left = useQuery({ queryKey: ["memberships", "guest-passes", member.id], queryFn: () => unwrap(api.GET("/api/v1/memberships/members/{member_id}/guest-passes", { params: { path: { member_id: member.id } } })) });
  const list = useQuery({ queryKey: ["memberships", "guests", member.id], queryFn: () => unwrap(api.GET("/api/v1/memberships/members/{member_id}/guests", { params: { path: { member_id: member.id } } })) });
  const bring = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/members/{member_id}/guests", { params: { path: { member_id: member.id } }, body: { guest_name: name.trim(), guest_phone: phone.trim() || null, branch_id: member.branch_id } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["memberships"] }); toast(t("guests.done", { name: name.trim() }), "ok"); setOpen(false); setName(""); setPhone(""); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <Card title={t("guests.title")} description={left.data ? t("guests.left", { count: left.data.left }) : undefined}
      actions={canManage && <Button variant="secondary" disabled={(left.data?.left ?? 0) <= 0} onClick={() => setOpen(true)}><UserPlus className="h-4 w-4" />{t("guests.bring")}</Button>}>
      <DataTable rows={list.data} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()} rowKey={(g) => g.id} dense
        empty={{ title: t("guests.empty"), hint: t("guests.emptyHint") }}
        columns={[
          { header: t("guests.guest"), cell: (g) => <span className="font-medium">{g.guest_name}</span> },
          { header: t("guests.phone"), hideBelow: "sm", cell: (g) => g.guest_phone ?? "—" },
          { header: t("date"), cell: (g) => formatDate(g.visited_on) },
        ]} />
      <Modal open={open} onClose={() => setOpen(false)} title={t("guests.bring")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>{t("cancel")}</Button><Button loading={bring.isPending} disabled={!name.trim()} onClick={() => bring.mutate()}>{t("guests.bring")}</Button></>}>
        <div className="space-y-4">
          <Field label={t("guests.guestName")} required><Input autoFocus value={name} maxLength={200} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label={t("guests.phone")}><Input type="tel" value={phone} maxLength={40} onChange={(e) => setPhone(e.target.value)} /></Field>
        </div>
      </Modal>
    </Card>
  );
}
