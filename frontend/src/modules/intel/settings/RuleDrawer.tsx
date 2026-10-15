import { useState } from "react";

import { Alert, ApiError, api, Button, Drawer, Field, Input, NumberInput, Select, toast, unwrap, useCompany, useMutation, useQueryClient, useTranslation } from "@/sdk";

import SchemaForm from "../actions/SchemaForm";
import { type ActionType, type Rule } from "../actions/logic";
import { editableFields, fieldsOf, toDraft, toValues, validate } from "../actions/schema";

/** Add a rule or change one: which action, when it may run by itself (the conditions) and how many times a day. */
export default function RuleDrawer({ companyId, rule, types, onClose }: { companyId: string; rule: Rule | null; types: ActionType[]; onClose: () => void }) {
  const { t } = useTranslation("intel");
  const qc = useQueryClient();
  const { company } = useCompany(companyId);
  const [typeCode, setTypeCode] = useState(rule?.action_type ?? "");
  const type = types.find((a) => a.type === typeCode);
  const fields = editableFields(fieldsOf(type?.rule_schema), true);
  const [draft, setDraft] = useState(() => (rule && type ? toDraft(fields, rule.conditions) : {}));
  const [cap, setCap] = useState(String(rule?.daily_cap ?? 10));
  const [note, setNote] = useState(rule?.note ?? "");
  const [checked, setChecked] = useState(false);
  const capNumber = Number(cap);
  const capOk = Number.isInteger(capNumber) && capNumber >= 1 && capNumber <= 1000;

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const conditions = toValues(fields, draft);
      return rule
        ? unwrap(api.PATCH("/api/v1/intel/automation/rules/{rule_id}", { params: { path: { rule_id: rule.id } }, body: { conditions, daily_cap: capNumber, note: note.trim() || null } }))
        : unwrap(api.POST("/api/v1/intel/automation/rules", { body: { company_id: companyId, action_type: typeCode, conditions, daily_cap: capNumber, note: note.trim() || null } }));
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["intel", "rules"] }); toast(t("rules.saved"), "ok"); onClose(); },
    onError: (e) => toast(e.message, "bad"),
  });

  const submit = () => {
    setChecked(true);
    if (!type || !capOk || Object.keys(validate(fields, draft)).length > 0) return;
    save.mutate();
  };
  const pick = (code: string) => {
    setTypeCode(code);
    const next = types.find((a) => a.type === code);
    setDraft(next ? toDraft(editableFields(fieldsOf(next.rule_schema), true), {}) : {});
  };

  return (
    <Drawer open onClose={onClose} title={rule ? t("rules.editTitle") : t("rules.addTitle")}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
          <Button loading={save.isPending} disabled={!type} form="rule-form" type="submit">{t("rules.save")}</Button>
        </>
      }>
      <form id="rule-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Field label={t("rules.action")} required>
          <Select value={typeCode} disabled={!!rule} onChange={(e) => pick(e.target.value)}>
            {!rule && <option value="">{t("rules.chooseAction")}</option>}
            {types.map((a) => <option key={a.type} value={a.type}>{a.title}</option>)}
          </Select>
        </Field>
        {type && (
          <>
            <p className="text-sm text-muted">{type.description}</p>
            <div className="space-y-2">
              <p className="text-sm font-medium">{t("rules.conditions")}</p>
              <p className="text-xs text-muted">{t("rules.conditionsHint")}</p>
              <SchemaForm fields={fields} draft={draft} onChange={(n, v) => setDraft((d) => ({ ...d, [n]: v }))} checked={checked}
                server={save.error instanceof ApiError ? save.error.fields : {}} branches={company?.branches} disabled={save.isPending} />
            </div>
            <Field label={t("rules.dailyLimit")} hint={t("rules.dailyLimitHint")} error={checked && !capOk ? t("schemaForm.range", { min: 1, max: 1000 }) : null} required>
              <NumberInput value={cap} inputMode="numeric" onChange={setCap} />
            </Field>
            <Field label={t("rules.note")} hint={t("rules.noteHint")}><Input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
            {save.error && <Alert tone="bad">{save.error.message}</Alert>}
          </>
        )}
      </form>
    </Drawer>
  );
}
