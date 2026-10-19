import { useState } from "react";

import { api, Button, Card, Field, Input, Modal, Select, toast, unwrap, useCan, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

import type { Member, Profile } from "../hooks";
import { CustomerPicker } from "../hooks";
import { personPath } from "../public";
import { Link } from "react-router-dom";

/** A household or company: members whose invoices go to one payer. Pick a group, or make one. */
export function HouseholdCard({ profile, customerId, companyId, member }: { profile: Profile; customerId: string; companyId: string; member?: Member }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const canManage = useCan("memberships.manage");
  const [making, setMaking] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"household" | "corporate">("household");
  const [payer, setPayer] = useState("");
  const groups = useQuery({ queryKey: ["memberships", "groups", companyId], queryFn: () => unwrap(api.GET("/api/v1/memberships/groups", { params: { query: { company_id: companyId } } })) });
  const current = useQuery({
    enabled: !!profile.group_id, queryKey: ["memberships", "group", profile.group_id],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/groups/{group_id}", { params: { path: { group_id: profile.group_id ?? "" } } })),
  });
  const done = () => { void qc.invalidateQueries({ queryKey: ["memberships"] }); };
  const setGroup = useMutation({
    meta: { silent: true }, onError: (e) => toast((e as Error).message, "bad"),
    mutationFn: (groupId: string | null) => unwrap(api.PUT("/api/v1/memberships/profiles/by-customer/{customer_id}/group", { params: { path: { customer_id: customerId } }, body: { group_id: groupId } })),
    onSuccess: () => { done(); toast(t("household.saved"), "ok"); },
  });
  const create = useMutation({
    meta: { silent: true }, onError: (e) => toast((e as Error).message, "bad"),
    mutationFn: async () => {
      const g = await unwrap(api.POST("/api/v1/memberships/groups", { body: { company_id: companyId, name: name.trim(), kind, payer_customer_id: payer || customerId } }));
      return unwrap(api.PUT("/api/v1/memberships/profiles/by-customer/{customer_id}/group", { params: { path: { customer_id: customerId } }, body: { group_id: g.id } }));
    },
    onSuccess: () => { done(); setMaking(false); setName(""); setPayer(""); toast(t("household.created"), "ok"); },
  });
  return (
    <Card title={t("household.title")} description={t("household.hint")}>
      <div className="space-y-3">
        <Field label={t("household.group")}>
          <Select value={profile.group_id ?? ""} disabled={!canManage || setGroup.isPending} onChange={(e) => setGroup.mutate(e.target.value || null)}>
            <option value="">{t("household.none")}</option>
            {groups.data?.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </Select>
        </Field>
        {groups.error && <p className="text-sm text-bad">{groups.error.message}</p>}
        {current.data && (
          <div className="rounded-lg bg-sunken p-3 text-sm">
            <p>{t("household.payer", { name: current.data.payer_name ?? "—" })}</p>
            <ul className="mt-2 space-y-1">
              {current.data.members.map((p) => <li key={p.id}><Link className="text-brand-strong hover:underline" to={personPath(p.customer_id)}>{p.customer_name ?? p.number}</Link></li>)}
            </ul>
          </div>
        )}
        {member?.billing_customer_name && <p className="text-sm text-muted">{t("household.invoicedTo", { name: member.billing_customer_name })}</p>}
        {canManage && <Button variant="secondary" onClick={() => setMaking(true)}>{t("household.make")}</Button>}
      </div>
      <Modal open={making} onClose={() => setMaking(false)} title={t("household.make")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setMaking(false)}>{t("cancel")}</Button><Button loading={create.isPending} disabled={!name.trim()} onClick={() => create.mutate()}>{t("household.create")}</Button></>}>
        <div className="space-y-4">
          <Field label={t("name")} required><Input value={name} maxLength={200} autoFocus onChange={(e) => setName(e.target.value)} /></Field>
          <Field label={t("household.kind")}>
            <Select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
              <option value="household">{t("household.kinds.household")}</option><option value="corporate">{t("household.kinds.corporate")}</option>
            </Select>
          </Field>
          <CustomerPicker value={payer} onChange={setPayer} label={t("household.payerLabel")} />
          <p className="text-xs text-muted">{t("household.payerHint")}</p>
        </div>
      </Modal>
    </Card>
  );
}
