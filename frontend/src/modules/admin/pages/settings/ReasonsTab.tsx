import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  api, ApiError, Badge, Button, Checkbox, DataTable, Drawer, ErrorText, Field, humanise, Input, Select, Switch, toast, unwrap, useCan, useFormState,
  useMutation, useQuery, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

type Reason = Schemas["ReasonOut"];
export const REASON_CATEGORIES = ["void", "refund", "discount", "price_override", "stock_adjustment", "write_off", "transfer_variance", "till_variance", "count_variance"];

export default function ReasonsTab() {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const canEdit = useCan("settings.manage");
  const [category, setCategory] = useState("");
  const [creating, setCreating] = useState(false);
  const reasons = useQuery({
    queryKey: ["reason-codes", category],
    queryFn: () => unwrap(api.GET("/api/v1/settings/reason-codes", { params: { query: { include_inactive: true, category: category || undefined } } })),
  });
  const toggle = useMutation({
    mutationFn: (r: Reason) => unwrap(api.POST("/api/v1/settings/reason-codes/{reason_id}/active", { params: { path: { reason_id: r.id } }, body: { active: !r.is_active } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["reason-codes"] }),
  });
  return (
    <>
      <p className="mb-3 text-sm text-muted">{t("reasonsHint")}</p>
      <DataTable
        rows={reasons.data} loading={reasons.isLoading} error={reasons.error?.message} onRetry={() => void reasons.refetch()} rowKey={(r) => r.id}
        searchText={(r) => `${r.code} ${r.label} ${r.category}`} searchPlaceholder={t("searchReasons")} pageSize={25}
        toolbar={
          <>
            <Select aria-label={t("category")} className="w-auto" value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">{t("allCategories")}</option>
              {REASON_CATEGORIES.map((c) => <option key={c} value={c}>{humanise(c)}</option>)}
            </Select>
            {canEdit && <Button className="ml-auto" onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("newReason")}</Button>}
          </>
        }
        empty={{ title: t("noReasons"), hint: t("noReasonsHint") }}
        columns={[
          { header: t("code"), sortValue: (r) => r.code, cell: (r) => <code className="text-xs font-semibold">{r.code}</code> },
          { header: t("label"), cell: (r) => <>{r.label}{r.requires_note && <Badge className="ml-2" tone="info">{t("noteRequired")}</Badge>}</> },
          { header: t("category"), hideBelow: "md", sortValue: (r) => r.category, cell: (r) => humanise(r.category) },
          {
            header: t("active"), align: "right",
            cell: (r) => <Switch label={`${t("active")}: ${r.code}`} checked={r.is_active} disabled={!canEdit || (toggle.isPending && toggle.variables?.id === r.id)} onChange={() => toggle.mutate(r)} />,
          },
        ]}
      />
      <NewReason open={creating} onClose={() => setCreating(false)} />
    </>
  );
}

function NewReason({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const f = useFormState({ category: REASON_CATEGORIES[0], code: "", label: "" });
  const [requiresNote, setRequiresNote] = useState(false);
  const create = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/settings/reason-codes", { body: { category: f.values.category, code: f.values.code.trim().toUpperCase(), label: f.values.label.trim(), requires_note: requiresNote } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["reason-codes"] }); toast(t("reasonSaved"), "ok"); f.reset(); setRequiresNote(false); onClose(); },
    onError: f.fail,
  });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };
  return (
    <Drawer open={open} onClose={onClose} title={t("newReason")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="new-reason" loading={create.isPending}>{t("save")}</Button></>}>
      <form id="new-reason" onSubmit={submit} className="space-y-4">
        <Field label={t("category")} error={f.error("category")}>
          <Select {...f.bind("category")}>{REASON_CATEGORIES.map((c) => <option key={c} value={c}>{humanise(c)}</option>)}</Select>
        </Field>
        <Field label={t("code")} hint={t("codeHint")} required error={f.error("code")}><Input {...f.bind("code")} required maxLength={30} className="uppercase" /></Field>
        <Field label={t("label")} required error={f.error("label")}><Input {...f.bind("label")} required maxLength={200} /></Field>
        <Checkbox label={t("requiresNote")} checked={requiresNote} onChange={(e) => setRequiresNote(e.target.checked)} />
        <ErrorText>{create.error instanceof ApiError && Object.keys(create.error.fields).length === 0 ? create.error.message : null}</ErrorText>
      </form>
    </Drawer>
  );
}
