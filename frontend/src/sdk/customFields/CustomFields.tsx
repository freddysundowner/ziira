import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError, errorMessage, unwrap } from "../api";
import { useTranslation } from "../i18n";
import { toast } from "../notify";
import { Alert, Button, Card, DetailList, ErrorState, Field, FormGrid, Input, Select, Skeleton, Textarea } from "../ui";
import { type CustomFieldDef, type CustomFieldProblem, type CustomValues, displayValue, toFormValues, toPayload, validateCustomValues, visibleFields } from "./logic";

const valuesKey = (entityType: string, entityId: string) => ["custom-field-values", entityType, entityId];
const defsKey = (entityType: string, companyId?: string) => ["custom-field-defs", entityType, companyId ?? ""];

/** The fields a business added to a kind of record (for a form that is creating one, before it has an id). */
export function useCustomFieldDefs(entityType: string, companyId?: string, enabled = true) {
  return useQuery({
    queryKey: defsKey(entityType, companyId),
    enabled,
    queryFn: () => unwrap(api.GET("/api/v1/custom-fields", { params: { query: { entity_type: entityType, company_id: companyId } } })),
  });
}

/** Save a record's custom field values (only the changed keys are sent). */
export function saveCustomValues(entityType: string, entityId: string, payload: Record<string, string | boolean | null>) {
  return unwrap(api.PUT("/api/v1/custom-fields/values/{entity_type}/{entity_id}", { params: { path: { entity_type: entityType, entity_id: entityId } }, body: { values: payload } }));
}

/** The inputs for a set of fields, controlled by the caller. `readOnly` shows the values as a list instead. */
export function CustomFieldsForm({ fields, values, onChange, problems = {}, readOnly = false, disabled = false }: {
  fields: readonly CustomFieldDef[]; values: CustomValues; onChange: (key: string, value: string) => void;
  problems?: Record<string, CustomFieldProblem>; readOnly?: boolean; disabled?: boolean;
}) {
  const { t } = useTranslation();
  const shown = visibleFields(fields);
  if (readOnly) {
    return <DetailList items={shown.map((f) => ({ label: f.label, value: displayValue(f, values[f.key] ?? "", t("customFields.yes"), t("customFields.no")) || <span className="text-muted">{t("customFields.notSet")}</span> }))} />;
  }
  const message = (key: string) => (problems[key] ? t(`customFields.problem.${problems[key]}`) : null);
  return (
    <FormGrid>
      {shown.map((f) => {
        const value = values[f.key] ?? "";
        const common = { disabled, "aria-label": undefined as string | undefined };
        return (
          <Field key={f.key} label={f.label} required={f.required} error={message(f.key)}>
            {f.kind === "choice" ? (
              <Select value={value} onChange={(e) => onChange(f.key, e.target.value)} {...common}>
                <option value="">{t("customFields.choose")}</option>
                {f.choices.map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
            ) : f.kind === "bool" ? (
              <Select value={value} onChange={(e) => onChange(f.key, e.target.value)} {...common}>
                <option value="">{t("customFields.choose")}</option>
                <option value="true">{t("customFields.yes")}</option>
                <option value="false">{t("customFields.no")}</option>
              </Select>
            ) : f.kind === "date" ? (
              <Input type="date" value={value} onChange={(e) => onChange(f.key, e.target.value)} {...common} />
            ) : f.kind === "number" ? (
              <Input inputMode="decimal" autoComplete="off" value={value} className="tnum text-right" {...common}
                onChange={(e) => { const v = e.target.value.replace(/,/g, "."); if (/^-?\d*\.?\d*$/.test(v)) onChange(f.key, v); }} />
            ) : value.length > 80 || value.includes("\n") ? (
              <Textarea value={value} maxLength={500} onChange={(e) => onChange(f.key, e.target.value)} {...common} />
            ) : (
              <Input value={value} maxLength={500} onChange={(e) => onChange(f.key, e.target.value)} {...common} />
            )}
          </Field>
        );
      })}
    </FormGrid>
  );
}

/**
 * The custom fields of one saved record, as a card: the values, and (when `canEdit`) an Edit button that opens the inputs with Save and Cancel.
 * Shows nothing when the business defined no fields for this kind of record, and nothing for someone who may not open the record.
 */
export function CustomFields({ entityType, entityId, canEdit = false, title }: { entityType: string; entityId: string; canEdit?: boolean; title?: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const key = valuesKey(entityType, entityId);
  const [draft, setDraft] = useState<CustomValues | null>(null);
  const [problems, setProblems] = useState<Record<string, CustomFieldProblem>>({});
  const [failure, setFailure] = useState<string | null>(null);
  const loaded = useQuery({
    queryKey: key,
    retry: false,
    queryFn: () => unwrap(api.GET("/api/v1/custom-fields/values/{entity_type}/{entity_id}", { params: { path: { entity_type: entityType, entity_id: entityId } } })),
  });
  const save = useMutation({
    meta: { silent: true },
    mutationFn: (payload: Record<string, string | boolean | null>) => saveCustomValues(entityType, entityId, payload),
    onSuccess: (data) => { qc.setQueryData(key, data); setDraft(null); setFailure(null); toast(t("customFields.saved"), "ok"); },
    onError: (e) => setFailure(errorMessage(e)),
  });

  if (loaded.isLoading) return <Skeleton className="h-24 rounded-xl" />;
  if (loaded.error instanceof ApiError && loaded.error.status === 403) return null;
  if (loaded.error) return <ErrorState title={t("customFields.loadFailed")} message={loaded.error.message} onRetry={() => void loaded.refetch()} />;
  const fields = loaded.data?.fields ?? [];
  if (fields.length === 0) return null;

  const saved = toFormValues(fields, loaded.data?.values ?? {});
  const submit = () => {
    const found = validateCustomValues(fields, draft ?? saved);
    setProblems(found);
    if (Object.keys(found).length > 0) return;
    const payload = toPayload(fields, draft ?? saved, saved);
    if (Object.keys(payload).length === 0) { setDraft(null); return; }
    setFailure(null);
    save.mutate(payload);
  };

  return (
    <Card title={title ?? t("customFields.title")}
      actions={canEdit && draft === null ? <Button size="sm" variant="secondary" onClick={() => { setDraft(saved); setProblems({}); }}>{t("customFields.edit")}</Button> : undefined}>
      {failure && <Alert tone="bad" className="mb-3">{failure}</Alert>}
      <CustomFieldsForm fields={fields} values={draft ?? saved} readOnly={draft === null} problems={problems} disabled={save.isPending}
        onChange={(k, v) => { setDraft((d) => ({ ...(d ?? saved), [k]: v })); setProblems((p) => Object.fromEntries(Object.entries(p).filter(([key]) => key !== k))); }} />
      {draft !== null && (
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => { setDraft(null); setFailure(null); }} disabled={save.isPending}>{t("customFields.cancel")}</Button>
          <Button onClick={submit} loading={save.isPending}>{t("customFields.save")}</Button>
        </div>
      )}
    </Card>
  );
}
