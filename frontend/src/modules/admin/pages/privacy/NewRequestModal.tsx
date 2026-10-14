import { type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import {
  api, Button, ErrorText, Field, FormGrid, Input, Modal, orNull, Select, Textarea, today, toast, unwrap, useCompany, useFormState, useMutation,
  useQueryClient, useTranslation,
} from "@/sdk";

import { REQUEST_TYPES, type RequestType } from "./model";

/** Record a person's request. The due date is worked out by the server from the company's response time. */
export default function NewRequestModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { company, companies } = useCompany();
  const f = useFormState({ company_id: "", request_type: "access", subject: "", notes: "", received_on: today() });
  const companyId = f.values.company_id || company?.id || "";

  const create = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/privacy/requests", {
      body: { company_id: companyId, request_type: f.values.request_type as RequestType, subject: f.values.subject.trim(), notes: orNull(f.values.notes), received_on: f.values.received_on || null },
    })),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["privacy-requests"] });
      toast(t("dsr.created", { number: r.number }), "ok");
      f.reset();
      onClose();
      navigate(`/admin/privacy/${r.id}`);
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });

  const submit = (e: FormEvent) => { e.preventDefault(); if (companyId && f.values.subject.trim()) create.mutate(); };
  return (
    <Modal open={open} onClose={onClose} title={t("dsr.newRequest")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button loading={create.isPending} disabled={!companyId || !f.values.subject.trim()} onClick={submit}>{t("dsr.record")}</Button></>}>
      <form className="space-y-4" onSubmit={submit}>
        <p className="text-sm text-muted">{t("dsr.verifyFirst")}</p>
        <FormGrid>
          <Field label={t("dsr.type")} error={f.error("request_type")}>
            <Select {...f.bind("request_type")}>{REQUEST_TYPES.map((x) => <option key={x} value={x}>{t(`dsr.typeName.${x}`)}</option>)}</Select>
          </Field>
          {companies.length > 1 && (
            <Field label={t("company")} error={f.error("company_id")}>
              <Select value={companyId} onChange={(e) => f.set("company_id", e.target.value)}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
            </Field>
          )}
        </FormGrid>
        <p className="-mt-2 text-xs text-muted">{t(`dsr.typeHint.${f.values.request_type}`)}</p>
        <Field label={t("dsr.subject")} hint={t("dsr.subjectHint")} error={f.error("subject")} required>
          <Input {...f.bind("subject")} maxLength={200} autoComplete="off" />
        </Field>
        <Field label={t("dsr.receivedOn")} error={f.error("received_on")}><Input type="date" max={today()} {...f.bind("received_on")} /></Field>
        <Field label={t("dsr.notes")} hint={t("dsr.notesHint")} error={f.error("notes")}><Textarea rows={3} maxLength={2000} {...f.bind("notes")} /></Field>
        <ErrorText>{create.error?.message}</ErrorText>
      </form>
    </Modal>
  );
}
