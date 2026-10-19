import { type FormEvent, useEffect, useState } from "react";

import { Alert, api, Attachments, Button, Field, FormGrid, Input, Modal, money, NumberInput, Switch, toast, today, unwrap, useFormState, useMutation, useQuery, useTranslation } from "@/sdk";

import { useRefresh, useSettings } from "../hooks";
import type { Expense, Project } from "../types";
import { ProjectPicker } from "./ProjectPicker";

const CATEGORIES = ["travel", "courtFees", "printing", "courier", "software", "accommodation", "other"] as const;

/** Add or change an expense (a disbursement) of the week: what was bought for a client's project, with an optional markup and a receipt photo. */
export function ExpenseDialog({ open, onClose, companyId, expense, day }: { open: boolean; onClose: () => void; companyId: string; expense?: Expense | null; day: string }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const settings = useSettings(companyId);
  const clients = useQuery({
    queryKey: ["timebilling", "clients", companyId], enabled: !!companyId && open,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/clients", { params: { query: { company_id: companyId } } })),
  });
  const f = useFormState({ date: day, description: "", amount: "", markup: "", reference: "", category: "" });
  const [project, setProject] = useState<Project | null>(null);
  const [billable, setBillable] = useState(true);
  const [saved, setSaved] = useState<Expense | null>(null);          // after saving, the receipt can be added
  const { reset, set } = f;
  useEffect(() => {
    if (!open) return;
    reset();
    set("date", expense?.expense_date ?? day);
    set("description", expense?.description ?? "");
    set("amount", expense?.amount ?? "");
    set("markup", expense ? expense.markup_percent : "");
    set("reference", expense?.reference ?? "");
    set("category", expense?.category ?? "");
    setBillable(expense?.billable ?? true);
    setProject(null);
    setSaved(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, expense?.id]);

  const projectId = project?.id ?? expense?.project_id ?? "";
  const clientId = project?.client_id;
  const usual = clients.data?.find((c) => c.customer_id === clientId)?.expense_markup_percent ?? settings.data?.default_markup_percent ?? "0";
  const limit = settings.data?.receipt_required_above;
  const needsReceipt = limit !== null && limit !== undefined && Number(f.values.amount) >= Number(limit);
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const body = {
        project_id: projectId, expense_date: f.values.date, description: f.values.description.trim(), amount: f.values.amount,
        markup_percent: f.values.markup === "" ? null : f.values.markup, billable, reference: f.values.reference.trim() || null, category: f.values.category.trim() || null,
      };
      return expense
        ? unwrap(api.PATCH("/api/v1/timebilling/expenses/{expense_id}", { params: { path: { expense_id: expense.id } }, body }))
        : unwrap(api.POST("/api/v1/timebilling/expenses", { body }));
    },
    onSuccess: (done) => { void refresh(); toast(t("expenses.saved"), "ok"); if (needsReceipt || !expense) setSaved(done as Expense); else onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (projectId) save.mutate(); };

  return (
    <Modal open={open} onClose={onClose} title={t(expense ? "expenses.editTitle" : "expenses.addTitle")}
      footer={saved ? <Button onClick={onClose}>{t("expenses.done")}</Button> : <><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="expense-form" loading={save.isPending} disabled={!projectId}>{t("save")}</Button></>}>
      {saved ? (
        <div className="space-y-3">
          <Alert tone={needsReceipt ? "warn" : "info"}>{t(needsReceipt ? "expenses.receiptNeeded" : "expenses.receiptOptional")}</Alert>
          <Attachments entityType="timebilling.expense" entityId={saved.id} title={t("expenses.receipt")} />
        </div>
      ) : (
        <form id="expense-form" onSubmit={submit} className="space-y-4">
          <Field label={t("projectField")} required error={f.error("project_id")}>
            <ProjectPicker companyId={companyId} value={projectId} label={project ? `${project.code} · ${project.name}` : expense ? `${expense.project_code} · ${expense.project_name}` : undefined} onChange={setProject} />
          </Field>
          <Field label={t("expenses.description")} required error={f.error("description")}><Input {...f.bind("description")} maxLength={300} required placeholder={t("expenses.descriptionHint")} /></Field>
          <FormGrid cols={3}>
            <Field label={t("date")} required error={f.error("expense_date")}><Input type="date" max={today()} {...f.bind("date")} required /></Field>
            <Field label={t("expenses.amount")} required error={f.error("amount")}><NumberInput value={f.values.amount} onChange={(v) => f.set("amount", v)} required /></Field>
            <Field label={t("expenses.markup")} hint={f.values.markup === "" ? t("expenses.markupUsual", { percent: usual }) : t("expenses.markupHint")} error={f.error("markup_percent")}>
              <NumberInput value={f.values.markup} onChange={(v) => f.set("markup", v)} placeholder={String(usual)} />
            </Field>
          </FormGrid>
          <FormGrid>
            <Field label={t("expenses.category")} error={f.error("category")}>
              <Input list="expense-categories" {...f.bind("category")} maxLength={60} placeholder={t("expenses.categoryHint")} />
              <datalist id="expense-categories">{CATEGORIES.map((c) => <option key={c} value={t(`expenses.cat.${c}`)} />)}</datalist>
            </Field>
            <Field label={t("expenses.reference")} error={f.error("reference")}><Input {...f.bind("reference")} maxLength={60} placeholder={t("expenses.referenceHint")} /></Field>
          </FormGrid>
          {needsReceipt && <p className="text-xs text-warn">{t("expenses.receiptRequiredAbove", { amount: money(String(limit)) })}</p>}
          <div className="flex items-center gap-2 text-sm"><Switch checked={billable} onChange={setBillable} label={t("expenses.billable")} />{t("expenses.billable")}</div>
        </form>
      )}
      {!saved && expense && <div className="mt-4"><Attachments entityType="timebilling.expense" entityId={expense.id} title={t("expenses.receipt")} /></div>}
    </Modal>
  );
}
