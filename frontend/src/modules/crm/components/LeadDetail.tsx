import { Pencil, UserCheck } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  api, Alert, Badge, Button, Card, DetailList, Drawer, Field, Input, Modal, Select, Textarea, toast, unwrap, useCan, useMutation, useQueryClient, useTranslation,
  type Schemas,
} from "@/sdk";

import { leadTone } from "../logic";
import { customerPath } from "../public";
import { FollowUps } from "./FollowUps";
import { LeadForm, useSources } from "./LeadForm";

type Lead = Schemas["LeadOut"];
const OPEN_STATUSES = ["new", "contacted", "qualified"] as const;

/** A lead in a drawer: move it along, mark it lost, turn it into a customer, see its follow-ups. */
export function LeadDetail({ lead, onClose }: { lead: Lead | null; onClose: () => void }) {
  const { t } = useTranslation("crm");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const can = useCan("leads.manage");
  const sources = useSources(!!lead);
  const [editing, setEditing] = useState(false);
  const [losing, setLosing] = useState(false);
  const [converting, setConverting] = useState(false);
  const [lostReason, setLostReason] = useState("");
  const [code, setCode] = useState("");
  const [group, setGroup] = useState("");
  const done = lead?.status === "converted";

  const setStatus = useMutation({
    mutationFn: (v: { status: "new" | "contacted" | "qualified" | "lost"; lost_reason?: string }) =>
      unwrap(api.POST("/api/v1/crm/leads/{lead_id}/status", { params: { path: { lead_id: lead?.id ?? "" } }, body: { status: v.status, lost_reason: v.lost_reason ?? null } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["leads"] }); toast(t("leadMoved"), "ok"); setLosing(false); setLostReason(""); onClose(); },
  });
  const convert = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/crm/leads/{lead_id}/convert", { params: { path: { lead_id: lead?.id ?? "" } }, body: { code: code.trim() || null, customer_group: group.trim() || null } })),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["leads"] });
      void qc.invalidateQueries({ queryKey: ["customers"] });
      toast(t("leadConverted", { name: r.customer.name }), "ok");
      setConverting(false);
      onClose();
      navigate(customerPath(r.customer.id));
    },
  });

  if (!lead) return null;
  const source = sources.data?.find((s) => s.id === lead.source_id);
  return (
    <>
      <Drawer open onClose={onClose} title={lead.name}
        footer={can && !done && lead.status !== "lost" ? <Button onClick={() => setConverting(true)}><UserCheck className="h-4 w-4" />{t("convertToCustomer")}</Button> : undefined}>
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={leadTone(lead.status)}>{t(`leadStatuses.${lead.status}`, lead.status)}</Badge>
            {can && !done && <Button size="sm" variant="secondary" onClick={() => setEditing(true)}><Pencil className="h-3.5 w-3.5" />{t("edit")}</Button>}
          </div>
          {lead.status === "lost" && lead.lost_reason && <Alert tone="warn">{t("lostBecause", { reason: lead.lost_reason })}</Alert>}
          {done && lead.converted_customer_id && (
            <Alert tone="ok">{t("alreadyCustomer")} <Button size="sm" variant="ghost" onClick={() => navigate(customerPath(lead.converted_customer_id ?? ""))}>{t("openCustomer")}</Button></Alert>
          )}
          <Card><DetailList items={[
            { label: t("businessName"), value: lead.business_name }, { label: t("phone"), value: lead.phone }, { label: t("email"), value: lead.email }, { label: t("source"), value: source?.name },
          ]} /></Card>
          {can && !done && (
            <Field label={t("stage")}>
              <Select value={lead.status === "lost" ? "lost" : lead.status} disabled={setStatus.isPending}
                onChange={(e) => (e.target.value === "lost" ? setLosing(true) : setStatus.mutate({ status: e.target.value as "new" }))}>
                {[...OPEN_STATUSES, "lost" as const].map((s) => <option key={s} value={s}>{t(`leadStatuses.${s}`)}</option>)}
              </Select>
            </Field>
          )}
          <FollowUps about={{ type: "lead", id: lead.id }} />
        </div>
      </Drawer>
      <LeadForm open={editing} onClose={() => setEditing(false)} lead={lead} />
      <Modal open={losing} onClose={() => setLosing(false)} title={t("markLost")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setLosing(false)}>{t("cancel")}</Button><Button variant="danger" loading={setStatus.isPending} onClick={() => setStatus.mutate({ status: "lost", lost_reason: lostReason.trim() })}>{t("markLost")}</Button></>}>
        <Field label={t("lostReason")} hint={t("lostReasonHint")}><Textarea value={lostReason} onChange={(e) => setLostReason(e.target.value)} maxLength={300} /></Field>
      </Modal>
      <Modal open={converting} onClose={() => setConverting(false)} title={t("convertToCustomer")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setConverting(false)}>{t("cancel")}</Button><Button loading={convert.isPending} onClick={() => convert.mutate()}>{t("convert")}</Button></>}>
        <p className="mb-4 text-sm text-muted">{t("convertExplain", { name: lead.name })}</p>
        <div className="space-y-4">
          <Field label={t("code")} hint={t("codeHint")}><Input value={code} onChange={(e) => setCode(e.target.value)} maxLength={20} /></Field>
          <Field label={t("group")} hint={t("groupHint")}><Input value={group} onChange={(e) => setGroup(e.target.value)} maxLength={60} /></Field>
        </div>
      </Modal>
    </>
  );
}
