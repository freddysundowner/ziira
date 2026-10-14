import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  Alert, api, Button, Card, DataTable, Drawer, Field, FormGrid, formatDate, Input, Modal, Select, Textarea, toast, unwrap, useCan, useFormState, useMutation,
  useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { ApprovalBar } from "./ApprovalBar";
import { Status } from "./Status";
import type { Bank } from "../types";

const CONFIRMATIONS = ["phone_callback", "in_person", "signed_letter"] as const;

/** A supplier's payment details. Changes go through three steps: propose, confirm with the supplier, approve. The full number is never shown. */
export function SupplierBankTab({ supplierId }: { supplierId: string }) {
  const { t } = useTranslation("purchasing");
  const qc = useQueryClient();
  const canEdit = useCan("supplier.bank_edit");
  const canConfirm = useCan("supplier.bank_confirm") || canEdit;
  const [proposing, setProposing] = useState(false);
  const [confirming, setConfirming] = useState<Bank | null>(null);
  const accounts = useQuery({ queryKey: ["purchasing", "banks", supplierId], queryFn: () => unwrap(api.GET("/api/v1/purchasing/suppliers/{supplier_id}/bank-accounts", { params: { path: { supplier_id: supplierId } } })) });
  const reject = useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/api/v1/purchasing/bank-accounts/{bank_id}/reject", { params: { path: { bank_id: id } } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["purchasing", "banks"] }); toast(t("bankRejected"), "ok"); },
  });
  const waiting = (accounts.data ?? []).find((b) => b.status === "pending_approval");

  return (
    <div className="space-y-4">
      <Alert tone="info">{t("bankProcess")}</Alert>
      {waiting && <ApprovalBar docType="supplier_bank_change" docId={waiting.id} waiting />}
      <Card title={t("bankDetails")} flush actions={canEdit && <Button size="sm" onClick={() => setProposing(true)}><Plus className="h-4 w-4" />{t("proposeBank")}</Button>}>
        <DataTable rows={accounts.data} loading={accounts.isLoading} error={accounts.error?.message} onRetry={() => void accounts.refetch()} rowKey={(b) => b.id}
          empty={{ title: t("noBank"), hint: canEdit ? t("noBankHint") : undefined }}
          columns={[
            { header: t("method"), cell: (b) => t(`methods.${b.method}`) },
            { header: t("bankName"), hideBelow: "sm", cell: (b) => b.bank_name ?? "—" },
            { header: t("accountName"), hideBelow: "md", cell: (b) => b.account_name ?? "—" },
            { header: t("accountNumber"), cell: (b) => <span className="font-mono text-xs">{b.account_no_masked ?? "—"}</span> },
            { header: t("since"), hideBelow: "md", cell: (b) => formatDate(b.valid_from) },
            { header: t("status"), cell: (b) => <Status status={b.status} /> },
            { header: "", align: "right", cell: (b) => b.status === "pending_confirmation" && canConfirm && (
              <span className="flex justify-end gap-2">
                <Button size="sm" variant="secondary" loading={reject.isPending && reject.variables === b.id} onClick={() => reject.mutate(b.id)}>{t("reject")}</Button>
                <Button size="sm" onClick={() => setConfirming(b)}>{t("confirmWithSupplier")}</Button>
              </span>
            ) },
          ]} />
      </Card>
      {proposing && <ProposeDrawer supplierId={supplierId} onClose={() => setProposing(false)} />}
      {confirming && <ConfirmModal bank={confirming} onClose={() => setConfirming(null)} />}
    </div>
  );
}

function ProposeDrawer({ supplierId, onClose }: { supplierId: string; onClose: () => void }) {
  const { t } = useTranslation("purchasing");
  const qc = useQueryClient();
  const f = useFormState({ method: "bank", account_no: "", bank_name: "", account_name: "" });
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/purchasing/suppliers/{supplier_id}/bank-accounts", { params: { path: { supplier_id: supplierId } }, body: {
      method: f.values.method as "bank", account_no: f.values.account_no.trim(), bank_name: f.values.bank_name.trim() || null, account_name: f.values.account_name.trim() || null } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["purchasing", "banks"] }); toast(t("bankProposed"), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Drawer open onClose={onClose} title={t("proposeBank")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="bank-form" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="bank-form" onSubmit={submit} className="space-y-4">
        <Alert tone="warn">{t("bankProposeWarn")}</Alert>
        <FormGrid>
          <Field label={t("method")} error={f.error("method")}>
            <Select {...f.bind("method")}><option value="bank">{t("methods.bank")}</option><option value="mobile_money">{t("methods.mobile_money")}</option></Select>
          </Field>
          <Field label={t("accountNumber")} required error={f.error("account_no")}><Input {...f.bind("account_no")} required maxLength={40} autoComplete="off" /></Field>
          <Field label={t("bankName")} error={f.error("bank_name")}><Input {...f.bind("bank_name")} maxLength={100} /></Field>
          <Field label={t("accountName")} error={f.error("account_name")}><Input {...f.bind("account_name")} maxLength={200} /></Field>
        </FormGrid>
      </form>
    </Drawer>
  );
}

function ConfirmModal({ bank, onClose }: { bank: Bank; onClose: () => void }) {
  const { t } = useTranslation("purchasing");
  const qc = useQueryClient();
  const [how, setHow] = useState<(typeof CONFIRMATIONS)[number]>("phone_callback");
  const [note, setNote] = useState("");
  const confirm = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/purchasing/bank-accounts/{bank_id}/confirm", { params: { path: { bank_id: bank.id } }, body: { confirmation_method: how, note: note.trim() || null } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["purchasing", "banks"] }); toast(t("bankConfirmed"), "ok"); onClose(); },
  });
  return (
    <Modal open onClose={onClose} title={t("confirmWithSupplier")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button loading={confirm.isPending} onClick={() => confirm.mutate()}>{t("confirm")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("confirmBankHint", { number: bank.account_no_masked ?? "" })}</p>
        <Field label={t("howConfirmed")}>
          <Select value={how} onChange={(e) => setHow(e.target.value as typeof how)}>{CONFIRMATIONS.map((c) => <option key={c} value={c}>{t(`confirmations.${c}`)}</option>)}</Select>
        </Field>
        <Field label={t("note")}><Textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} /></Field>
      </div>
    </Modal>
  );
}
