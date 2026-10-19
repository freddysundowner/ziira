import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  api, Button, Card, CustomFieldsForm, Field, Input, PageHeader, Select, Skeleton, Textarea, toPayload, unwrap, useCustomFieldDefs,
  useMutation, useTranslation, validateCustomValues, saveCustomValues, toast, type CustomFieldProblem, type CustomValues,
} from "@/sdk";

import { PersonSelect } from "../components/pickers";
import { ItemHistory } from "../components/ItemHistory";
import { ReceiveChecklist } from "../components/ReceiveChecklist";
import { ReceiveCustomer } from "../components/ReceiveCustomer";
import { ReceiveIntake } from "../components/ReceiveIntake";
import { ReceiveItem } from "../components/ReceiveItem";
import { useAsset, useBranchChoice, useJobsCompany, useRefreshJobs } from "../hooks";
import { jobHref } from "../public";
import { buildJobBody, emptyReceive, receiveProblems, type ReceiveForm } from "../receive";

/** The counter form: take an item in. Kept short, one column on a phone, big touch targets. */
export default function ReceivePage() {
  const { t } = useTranslation("jobs");
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { companyId, branches, isLoading, currency } = useJobsCompany();
  const { branchId, setBranchId } = useBranchChoice(branches);
  const refresh = useRefreshJobs();
  const [form, setForm] = useState<ReceiveForm>(() => ({ ...emptyReceive(), customerId: params.get("customer") ?? "", assetId: params.get("asset") ?? "" }));
  const [values, setValues] = useState<CustomValues>({});
  const [tried, setTried] = useState(false);
  const [key] = useState(() => crypto.randomUUID());       // one per time the form opens: a retry never makes a second job
  const fields = useCustomFieldDefs("jobs.work_order", companyId, !!companyId);
  const chosen = useAsset(params.get("asset"));
  const update = (patch: Partial<ReceiveForm>) => setForm((f) => ({ ...f, ...patch }));
  const current: ReceiveForm = { ...form, branchId: form.branchId || branchId };
  const picked = useAsset(current.itemMode === "existing" ? current.assetId : null);
  const lastReading = picked.data?.odometer ? Number(picked.data.odometer) : undefined;

  useEffect(() => {          // an item opened from its page brings its owner along
    const owner = chosen.data?.customer_id;
    if (owner) setForm((f) => (f.customerId ? f : { ...f, customerId: owner }));
  }, [chosen.data]);

  const problems = receiveProblems(current);
  const customProblems: Record<string, CustomFieldProblem> = useMemo(() => validateCustomValues(fields.data ?? [], values), [fields.data, values]);
  const save = useMutation({
    meta: { silent: true },
    mutationFn: async () => {
      const job = await unwrap(api.POST("/api/v1/jobs/jobs", { params: { header: { "Idempotency-Key": key } }, body: buildJobBody(companyId, current) }));
      const extra = toPayload(fields.data ?? [], values, {});
      if (Object.keys(extra).length > 0) await saveCustomValues("jobs.work_order", job.id, extra).catch(() => toast(t("receive.customFailed"), "bad"));
      return job;
    },
    onSuccess: (job) => { void refresh(); toast(t("receive.done", { number: job.number }), "ok"); navigate(jobHref(job.id)); },
    onError: (e) => toast(e.message, "bad"),
  });
  const submit = () => {
    setTried(true);
    if (problems.length > 0 || Object.keys(customProblems).length > 0) return;
    save.mutate();
  };

  if (isLoading) return <Skeleton className="h-96" />;
  return (
    <form onSubmit={(e) => { e.preventDefault(); submit(); }} className="mx-auto max-w-2xl">
      <PageHeader title={t("menu.receive")} description={t("receive.hint")} back={{ to: "/jobs", label: t("menu.jobs") }} />
      <div className="space-y-4">
        <Card title={t("receive.what")}>
          <div className="space-y-4">
            <Field label={t("receive.title")} hint={t("receive.titleHint")} required error={tried && problems.includes("title") ? t("receive.titleNeeded") : null}>
              <Input className="h-11" maxLength={200} autoFocus value={form.title} onChange={(e) => update({ title: e.target.value })} />
            </Field>
            <Field label={t("receive.details")}><Textarea maxLength={4000} value={form.description} onChange={(e) => update({ description: e.target.value })} /></Field>
            <Field label={t("receive.condition")} hint={t("receive.conditionHint")}><Textarea maxLength={4000} value={form.condition} onChange={(e) => update({ condition: e.target.value })} /></Field>
          </div>
        </Card>
        <Card title={t("receive.customerTitle")}><ReceiveCustomer form={current} update={update} /></Card>
        <Card title={t("receive.item")}><ReceiveItem form={current} update={update} problems={tried ? problems : []} /></Card>
        {current.itemMode === "existing" && current.assetId && <ItemHistory assetId={current.assetId} currency={currency} />}
        <Card title={t("garage.receive.intake")}><ReceiveIntake companyId={companyId} form={current} update={update} hint={lastReading ? t("garage.receive.lastReading", { reading: lastReading }) : undefined} /></Card>
        <Card title={t("receive.plan")}>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("receive.promised")}><Input className="h-11" type="date" value={form.promised} onChange={(e) => update({ promised: e.target.value })} /></Field>
            <Field label={t("receive.assignee")}><PersonSelect value={form.assigneeId} onChange={(id) => update({ assigneeId: id })} /></Field>
            {branches.length > 1 && (
              <Field label={t("receive.branch")} required>
                <Select className="h-11" value={current.branchId} onChange={(e) => { update({ branchId: e.target.value }); setBranchId(e.target.value); }}>
                  {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                </Select>
              </Field>
            )}
          </div>
        </Card>
        <Card title={t("receive.checklist")} description={t("receive.checklistHint")}><ReceiveChecklist companyId={companyId} form={current} update={update} /></Card>
        {!!fields.data?.length && (
          <Card title={t("receive.more")}>
            <CustomFieldsForm fields={fields.data} values={values} problems={tried ? customProblems : {}} onChange={(k, v) => setValues((x) => ({ ...x, [k]: v }))} />
          </Card>
        )}
        <div className="sticky bottom-0 -mx-4 flex justify-end gap-2 border-t border-line bg-surface/95 px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:p-0">
          <Button variant="secondary" size="lg" onClick={() => navigate("/jobs")}>{t("common.cancel")}</Button>
          <Button size="lg" type="submit" loading={save.isPending}>{t("receive.save")}</Button>
        </div>
      </div>
    </form>
  );
}
