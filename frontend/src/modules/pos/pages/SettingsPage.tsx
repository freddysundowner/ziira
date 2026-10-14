import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  api, ApiError, Button, Card, Checkbox, DataTable, Drawer, ErrorState, Field, Input, PageHeader, Schemas, Select, Switch, toast, unwrap, useCompany, useFormState, useMutation,
  useQuery, useQueryClient, useTranslation,
} from "@/sdk";

const CATEGORIES = ["void", "sale_return", "price_override", "till_variance"] as const;
type Category = (typeof CATEGORIES)[number];

/** Selling policies the business can change: what receipts say at the foot, and the lists of reasons cashiers choose from. */
export default function SettingsPage() {
  const { t } = useTranslation("pos");
  return (
    <>
      <PageHeader title={t("settings")} description={t("settingsHint")} />
      <div className="space-y-4">
        <ReceiptFooters />
        {CATEGORIES.map((c) => <ReasonList key={c} category={c} />)}
      </div>
    </>
  );
}

function ReceiptFooters() {
  const { t } = useTranslation("pos");
  const qc = useQueryClient();
  const { company, companies } = useCompany();
  const [companyId, setCompanyId] = useState("");
  const id = companyId || company?.id || "";
  const [draft, setDraft] = useState<{ receipt_footer?: string; invoice_footer?: string }>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const settings = useQuery({ enabled: Boolean(id), queryKey: ["company-settings", id], queryFn: () => unwrap(api.GET("/api/v1/companies/{company_id}/settings", { params: { path: { company_id: id } } })) });
  const receipt = draft.receipt_footer ?? settings.data?.receipt_footer ?? "";
  const invoice = draft.invoice_footer ?? settings.data?.invoice_footer ?? "";
  const dirty = settings.data !== undefined && (receipt !== settings.data.receipt_footer || invoice !== settings.data.invoice_footer);

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.PATCH("/api/v1/companies/{company_id}/settings", { params: { path: { company_id: id } }, body: { receipt_footer: receipt.trim(), invoice_footer: invoice.trim() } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["company-settings", id] }); setDraft({}); setErrors({}); toast(t("saved"), "ok"); },
    onError: (e) => { setErrors(e instanceof ApiError ? e.fields : {}); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Card title={t("receiptText")} description={t("receiptTextHint")}>
      {settings.error ? (
        <ErrorState message={settings.error.message} onRetry={() => void settings.refetch()} />
      ) : (
        <form onSubmit={submit} className="max-w-xl space-y-4">
          {companies.length > 1 && (
            <Field label={t("company")}><Select value={id} onChange={(e) => { setCompanyId(e.target.value); setDraft({}); }}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
          )}
          <Field label={t("receiptFooter")} hint={t("footerHint")} error={errors.receipt_footer}>
            <Input value={receipt} maxLength={200} disabled={settings.isLoading} onChange={(e) => setDraft((d) => ({ ...d, receipt_footer: e.target.value }))} />
          </Field>
          <Field label={t("invoiceFooter")} hint={t("footerHint")} error={errors.invoice_footer}>
            <Input value={invoice} maxLength={200} disabled={settings.isLoading} onChange={(e) => setDraft((d) => ({ ...d, invoice_footer: e.target.value }))} />
          </Field>
          <Button type="submit" loading={save.isPending} disabled={!dirty}>{t("save")}</Button>
        </form>
      )}
    </Card>
  );
}

function ReasonList({ category }: { category: Category }) {
  const { t } = useTranslation("pos");
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const reasons = useQuery({ queryKey: ["reasons-all", category], queryFn: () => unwrap(api.GET("/api/v1/settings/reason-codes", { params: { query: { category, include_inactive: true } } })) });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["reasons-all", category] }); void qc.invalidateQueries({ queryKey: ["reasons", category] }); };

  const toggle = useMutation({
    mutationFn: (r: Schemas["ReasonOut"]) => unwrap(api.POST("/api/v1/settings/reason-codes/{reason_id}/active", { params: { path: { reason_id: r.id } }, body: { active: !r.is_active } })),
    onSuccess: refresh,
  });

  return (
    <Card title={t(`reasonLists.${category}`)} description={t(`reasonListHints.${category}`)} flush
      actions={<Button size="sm" variant="secondary" onClick={() => setAdding(true)}><Plus className="h-4 w-4" />{t("addReason")}</Button>}>
      <DataTable rows={reasons.data} loading={reasons.isLoading} error={reasons.error?.message} onRetry={() => void reasons.refetch()} rowKey={(r) => r.id}
        empty={{ title: t("noReasons"), hint: t("noReasonsHint") }}
        columns={[
          { header: t("code"), hideBelow: "sm", cell: (r) => <span className="font-mono text-xs">{r.code}</span> },
          { header: t("label"), cell: (r) => <span className={r.is_active ? "" : "text-muted line-through"}>{r.label}</span> },
          { header: t("noteRequired"), hideBelow: "md", cell: (r) => (r.requires_note ? t("yes") : t("no")) },
          { header: t("active"), align: "right", cell: (r) => <Switch label={t("active")} checked={r.is_active} disabled={toggle.isPending} onChange={() => toggle.mutate(r)} /> },
        ]} />
      <NewReason category={category} open={adding} onClose={() => setAdding(false)} onSaved={refresh} />
    </Card>
  );
}

function NewReason({ category, open, onClose, onSaved }: { category: Category; open: boolean; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation("pos");
  const f = useFormState({ code: "", label: "" });
  const [requiresNote, setRequiresNote] = useState(false);
  const create = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/settings/reason-codes", { body: { category, code: f.values.code.trim().toUpperCase(), label: f.values.label.trim(), requires_note: requiresNote } })),
    onSuccess: () => { onSaved(); toast(t("saved"), "ok"); f.reset(); setRequiresNote(false); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };
  return (
    <Drawer open={open} onClose={onClose} title={t("addReason")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form={`reason-${category}`} loading={create.isPending}>{t("save")}</Button></>}>
      <form id={`reason-${category}`} onSubmit={submit} className="space-y-4">
        <Field label={t("label")} required error={f.error("label")}><Input {...f.bind("label")} required autoFocus maxLength={120} /></Field>
        <Field label={t("code")} required error={f.error("code")} hint={t("reasonCodeHint")}><Input {...f.bind("code")} required maxLength={30} className="font-mono uppercase" /></Field>
        <Checkbox label={t("noteRequiredLabel")} checked={requiresNote} onChange={(e) => setRequiresNote(e.target.checked)} />
      </form>
    </Drawer>
  );
}
