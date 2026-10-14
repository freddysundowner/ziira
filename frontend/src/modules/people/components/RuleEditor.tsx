import { type FormEvent, useState } from "react";

import {
  Alert, api, Button, Card, Checkbox, ErrorText, Field, FormGrid, Input, Modal, NumberInput, Select, toast, today, unwrap, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { APPLIES, BASES, buildDefinition, emptyRule, KINDS, problems, type RuleForm } from "../lib/rules";
import { RuleSummary, RuleTryIt } from "./RuleSummary";
import { SideEditor } from "./SideEditor";

/** Define a statutory rule (a tax, contribution, levy ...), or a new version of one from a date. The body mounts only while open. */
export function RuleEditor({ open, onClose, companyId, currency, initial }: { open: boolean; onClose: () => void; companyId: string; currency?: string; initial?: RuleForm }) {
  return open ? <Body onClose={onClose} companyId={companyId} currency={currency} initial={initial} /> : null;
}

function Body({ onClose, companyId, currency, initial }: { onClose: () => void; companyId: string; currency?: string; initial?: RuleForm }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const isVersion = !!initial;
  const [form, setForm] = useState<RuleForm>(() => (initial ? { ...initial, effectiveFrom: today(), effectiveTo: "", sourceReference: "" } : emptyRule(today())));
  const [tryBase, setTryBase] = useState("");
  const [shown, setShown] = useState(false);
  const patch = (p: Partial<RuleForm>) => setForm((f) => ({ ...f, ...p }));
  const found = problems(form);

  // The payable account needs the finance unit; when it is off or not readable by this user, the field is simply left out.
  const accounts = useQuery({
    retry: false, queryKey: ["people", "liability-accounts", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/finance/accounts", { params: { query: { company_id: companyId } } })),
  });
  const liabilities = (accounts.data ?? []).filter((a) => a.type === "liability" && a.is_active && !a.is_control);

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/people/rules", { body: {
      company_id: companyId, code: form.code.trim().toUpperCase(), effective_from: form.effectiveFrom, effective_to: form.effectiveTo || null,
      definition: buildDefinition(form), source_reference: form.sourceReference.trim(), payable_account_id: form.payableAccountId || null } })),
    onSuccess: (r) => { void qc.invalidateQueries({ queryKey: ["people", "rules"] }); toast(t("rules.saved", { code: r.code }), "ok"); onClose(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); setShown(true); if (found.length === 0) save.mutate(); };
  const err = (key: string) => (shown && found.includes(key) ? t(`rules.problem.${key}`) : null);

  return (
    <Modal open onClose={onClose} size="lg" title={isVersion ? t("rules.newVersionOf", { code: form.code }) : t("rules.new")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="rule-form" loading={save.isPending}>{t("rules.save")}</Button></>}>
      <form id="rule-form" onSubmit={submit} className="space-y-4">
        <Alert tone="info">{t("rules.saveInfo")}</Alert>
        <FormGrid>
          <Field label={t("rules.code")} hint={t("rules.codeHint")} required error={err("code")}>
            <Input value={form.code} disabled={isVersion} onChange={(e) => patch({ code: e.target.value.toUpperCase() })} maxLength={20} autoFocus={!isVersion} />
          </Field>
          <Field label={t("rules.name")} hint={t("rules.nameHint")} required error={err("name")}><Input value={form.name} onChange={(e) => patch({ name: e.target.value })} maxLength={100} /></Field>
          <Field label={t("rules.kind")}>
            <Select value={form.kind} onChange={(e) => patch({ kind: e.target.value as RuleForm["kind"] })}>{KINDS.map((k) => <option key={k} value={k}>{t(`rules.kinds.${k}`)}</option>)}</Select>
          </Field>
          <Field label={t("rules.order")} hint={t("rules.orderHint")}><NumberInput value={form.order} onChange={(v) => patch({ order: v.replace(/\..*/, "") })} /></Field>
        </FormGrid>
        <Field label={t("rules.source")} hint={t("rules.sourceHint")} required error={err("source")}>
          <Input value={form.sourceReference} onChange={(e) => patch({ sourceReference: e.target.value })} maxLength={500} />
        </Field>
        <FormGrid>
          <Field label={t("rules.effectiveFrom")} required error={err("from")}><Input type="date" value={form.effectiveFrom} onChange={(e) => patch({ effectiveFrom: e.target.value })} /></Field>
          <Field label={t("rules.effectiveTo")} hint={t("rules.effectiveToHint")} error={err("range")}><Input type="date" value={form.effectiveTo} min={form.effectiveFrom} onChange={(e) => patch({ effectiveTo: e.target.value })} /></Field>
          <Field label={t("rules.base")} hint={t(`rules.baseHint.${form.base}`)}>
            <Select value={form.base} onChange={(e) => patch({ base: e.target.value as RuleForm["base"] })}>{BASES.map((b) => <option key={b} value={b}>{t(`rules.bases.${b}`)}</option>)}</Select>
          </Field>
          <Field label={t("rules.appliesTo")}>
            <Select value={form.appliesTo} onChange={(e) => patch({ appliesTo: e.target.value as RuleForm["appliesTo"] })}>{APPLIES.map((a) => <option key={a} value={a}>{t(`rules.applies.${a}`)}</option>)}</Select>
          </Field>
        </FormGrid>
        <div>
          <Checkbox label={t("rules.reduces")} checked={form.reducesTaxable} disabled={form.employee.method === "none"} onChange={(e) => patch({ reducesTaxable: e.target.checked })} />
          <p className="ml-6 mt-0.5 text-xs text-muted">{t("rules.reducesHint")}</p>
          <ErrorText>{err("reduceTaxable")}</ErrorText>
        </div>
        {liabilities.length > 0 && (
          <Field label={t("rules.payableAccount")} hint={t("rules.payableAccountHint")}>
            <Select value={form.payableAccountId} onChange={(e) => patch({ payableAccountId: e.target.value })}>
              <option value="">{t("rules.defaultAccount")}</option>{liabilities.map((a) => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}
            </Select>
          </Field>
        )}
        <SideEditor who="employee" value={form.employee} onChange={(employee) => patch({ employee, reducesTaxable: employee.method === "none" ? false : form.reducesTaxable })} currency={currency} />
        <SideEditor who="employer" value={form.employer} onChange={(employer) => patch({ employer })} currency={currency} />
        <ErrorText>{shown ? ["noParts", "rate", "amount", "bandRate", "bandOrder"].filter((k) => found.includes(k)).map((k) => t(`rules.problem.${k}`)).join(" · ") : null}</ErrorText>
        <Card title={t("rules.howItWorks")}><RuleSummary form={form} currency={currency} /></Card>
        <RuleTryIt form={form} base={tryBase} onBase={setTryBase} currency={currency} />
      </form>
    </Modal>
  );
}
