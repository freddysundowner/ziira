import { type FormEvent } from "react";

import {
  api, ApiError, Button, Drawer, ErrorText, Field, FormGrid, Input, orNull, toast, unwrap, useFormState, useMutation, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

type Branch = Schemas["BranchSummary"];

/** Add a branch to a company, or edit one. Mount it only while open. */
export function BranchDrawer({ companyId, branch, onClose }: { companyId: string; branch: Branch | null; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const f = useFormState({ code: branch?.code ?? "", name: branch?.name ?? "", address: branch?.address ?? "", phone: branch?.phone ?? "" });

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const v = f.values;
      const body = { code: v.code.trim(), name: v.name.trim(), address: orNull(v.address), phone: orNull(v.phone) };
      return branch
        ? unwrap(api.PATCH("/api/v1/branches/{branch_id}", { params: { path: { branch_id: branch.id } }, body }))
        : unwrap(api.POST("/api/v1/companies/{company_id}/branches", { params: { path: { company_id: companyId } }, body }));
    },
    onSuccess: (b) => {
      void qc.invalidateQueries({ queryKey: ["organisation"] });
      void qc.invalidateQueries({ queryKey: ["companies"] });
      toast(t(branch ? "org.branchSaved" : "org.branchAdded", { name: b.name }), "ok");
      onClose();
    },
    onError: (e) => { f.fail(e); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Drawer open onClose={onClose} title={branch ? t("org.editBranch") : t("org.addBranch")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="branch-form" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="branch-form" onSubmit={submit} className="space-y-4">
        <FormGrid>
          <Field label={t("org.branchCode")} required error={f.error("code")} hint={t("org.branchCodeHint")}><Input {...f.bind("code")} required maxLength={10} className="uppercase" autoFocus /></Field>
          <Field label={t("org.branchName")} required error={f.error("name")}><Input {...f.bind("name")} required /></Field>
        </FormGrid>
        <Field label={t("org.address")} error={f.error("address")}><Input {...f.bind("address")} /></Field>
        <Field label={t("phone")} error={f.error("phone")}><Input type="tel" {...f.bind("phone")} /></Field>
        <ErrorText>{save.error instanceof ApiError && Object.keys(save.error.fields).length === 0 ? save.error.message : null}</ErrorText>
      </form>
    </Drawer>
  );
}
