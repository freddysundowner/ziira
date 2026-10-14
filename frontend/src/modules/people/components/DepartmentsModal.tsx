import { type FormEvent, useState } from "react";

import { api, Button, Input, Modal, toast, unwrap, useCan, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { useDepartments } from "../lib/lookups";

export function DepartmentsModal({ open, onClose, companyId }: { open: boolean; onClose: () => void; companyId: string }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const canManage = useCan("employees.manage");
  const [name, setName] = useState("");
  const departments = useDepartments(companyId);
  const add = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/people/departments", { body: { company_id: companyId, name: name.trim() } })),
    onSuccess: (d) => { void qc.invalidateQueries({ queryKey: ["people", "departments"] }); toast(t("dept.added", { name: d.name }), "ok"); setName(""); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (name.trim()) add.mutate(); };
  return (
    <Modal open={open} onClose={onClose} title={t("dept.title")} size="sm" footer={<Button variant="secondary" onClick={onClose}>{t("close")}</Button>}>
      {departments.error ? <p className="text-sm text-bad">{departments.error.message}</p> : (departments.data ?? []).length === 0 ? (
        <p className="mb-4 text-sm text-muted">{t("dept.empty")}</p>
      ) : (
        <ul className="mb-4 divide-y divide-line rounded-xl border border-line">
          {(departments.data ?? []).map((d) => <li key={d.id} className="px-3 py-2 text-sm">{d.name}</li>)}
        </ul>
      )}
      {canManage && (
        <form onSubmit={submit} className="flex items-start gap-2">
          <Input aria-label={t("dept.name")} placeholder={t("dept.name")} value={name} onChange={(e) => setName(e.target.value)} maxLength={100} />
          <Button type="submit" loading={add.isPending} disabled={!name.trim()}>{t("add")}</Button>
        </form>
      )}
    </Modal>
  );
}
