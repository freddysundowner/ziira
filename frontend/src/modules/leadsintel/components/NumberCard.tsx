import { type FormEvent, useState } from "react";

import { api, Alert, Badge, Button, Card, ConfirmDialog, Field, FormGrid, Input, Spinner, toast, unwrap, useCompany, useFormState, useMutation, useQuery, useQueryClient, useTranslation, type Schemas } from "@/sdk";

import { canStartAgain, digits, isWorking } from "../logic";

type State = Schemas["LeadIntelStateOut"];
type Mode = "new" | "existing";

/** Step 2: connect a number. A new one is set up by Lead Intel with Meta (it takes a while: we ask every few seconds);
 *  one already on Lead Intel is claimed with a code Lead Intel sends to it by SMS. */
export default function NumberCard({ companyId, state }: { companyId: string; state: State }) {
  const { t } = useTranslation("leadsintel");
  const status = state.whatsapp?.status;
  return (
    <Card title={t("numberTitle")} description={t("numberHint")} actions={status ? <Badge tone={status === "failed" ? "bad" : "info"}>{t(`status.${status}`, { defaultValue: status })}</Badge> : undefined}>
      {status === "code_sent" ? <ClaimCode companyId={companyId} sentTo={state.sent_to ?? null} />
        : isWorking(status) ? <Progress companyId={companyId} state={state} />
        : canStartAgain(status) ? <Start companyId={companyId} previous={state} /> : null}
    </Card>
  );
}

function Start({ companyId, previous }: { companyId: string; previous: State }) {
  const { t } = useTranslation("leadsintel");
  const { company } = useCompany();
  const [mode, setMode] = useState<Mode>("new");
  const failed = previous.whatsapp;
  return (
    <div className="space-y-4">
      {failed && failed.status === "failed" && <Alert tone="bad">{t("failed", { code: failed.error_code ?? "", message: failed.error_message ?? "" })}</Alert>}
      <div className="flex gap-2" role="radiogroup" aria-label={t("numberTitle")}>
        {(["new", "existing"] as const).map((m) => (
          <Button key={m} variant={mode === m ? "primary" : "secondary"} size="sm" role="radio" aria-checked={mode === m} onClick={() => setMode(m)}>{t(`mode.${m}`)}</Button>
        ))}
      </div>
      {mode === "new" ? <NewNumber companyId={companyId} companyName={company?.name ?? ""} /> : <ExistingNumber companyId={companyId} />}
    </div>
  );
}

function NewNumber({ companyId, companyName }: { companyId: string; companyName: string }) {
  const { t } = useTranslation("leadsintel");
  const qc = useQueryClient();
  const f = useFormState({ country_code: "", phone_number: "", business_name: companyName, display_name: companyName, about: "" });
  const start = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/plugins/leadsintel/whatsapp/connect", { body: {
      company_id: companyId, country_code: digits(f.values.country_code), phone_number: digits(f.values.phone_number),
      business_name: f.values.business_name.trim(), display_name: f.values.display_name.trim(), about: f.values.about.trim() || null } })),
    onSuccess: () => { toast(t("requested"), "ok"); void qc.invalidateQueries({ queryKey: ["leadsintel-state"] }); },
    onError: (e) => { f.fail(e); toast(e.message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); start.mutate(); };
  return (
    <form onSubmit={submit} className="space-y-4">
      <p className="text-sm text-muted">{t("newHint")}</p>
      <FormGrid>
        <Field label={t("countryCode")} hint={t("countryCodeHint")} error={f.error("country_code")}><Input inputMode="numeric" required {...f.bind("country_code")} /></Field>
        <Field label={t("phone")} hint={t("phoneHint")} error={f.error("phone_number")}><Input type="tel" inputMode="numeric" required {...f.bind("phone_number")} /></Field>
        <Field label={t("businessName")} error={f.error("business_name")}><Input required maxLength={100} {...f.bind("business_name")} /></Field>
        <Field label={t("displayName")} hint={t("displayNameHint")} error={f.error("display_name")}><Input required maxLength={100} {...f.bind("display_name")} /></Field>
      </FormGrid>
      <Field label={t("about")} hint={t("aboutHint")} error={f.error("about")}><Input maxLength={139} {...f.bind("about")} /></Field>
      <Button type="submit" loading={start.isPending}>{t("connect")}</Button>
    </form>
  );
}

function ExistingNumber({ companyId }: { companyId: string }) {
  const { t } = useTranslation("leadsintel");
  const qc = useQueryClient();
  const f = useFormState({ country_code: "", phone_number: "" });
  const body = { company_id: companyId, country_code: digits(f.values.country_code), phone_number: digits(f.values.phone_number) };
  const check = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/plugins/leadsintel/whatsapp/existing", { body })),
    onError: (e) => toast(e.message, "bad"),
  });
  const claim = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/plugins/leadsintel/whatsapp/claim", { body })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["leadsintel-state"] }); toast(t("codeSent"), "ok"); },
    onError: (e) => toast(e.message, "bad"),
  });
  const found = check.data;
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">{t("existingHint")}</p>
      <FormGrid>
        <Field label={t("countryCode")} hint={t("countryCodeHint")}><Input inputMode="numeric" {...f.bind("country_code")} /></Field>
        <Field label={t("phone")} hint={t("phoneHint")}><Input type="tel" inputMode="numeric" {...f.bind("phone_number")} /></Field>
      </FormGrid>
      <Button variant="secondary" loading={check.isPending} disabled={!digits(f.values.country_code) || digits(f.values.phone_number).length < 5} onClick={() => check.mutate()}>{t("checkNumber")}</Button>
      {found && (found.claimable
        ? <Alert tone="ok"><span className="mr-3">{t("claimable")}</span><Button size="sm" loading={claim.isPending} onClick={() => claim.mutate()}>{t("sendCode")}</Button></Alert>
        : <Alert tone="warn">{t(`notClaimable.${found.reason ?? "other"}`, { defaultValue: t("notClaimable.other") })}</Alert>)}
    </div>
  );
}

function ClaimCode({ companyId, sentTo }: { companyId: string; sentTo: string | null }) {
  const { t } = useTranslation("leadsintel");
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const verify = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/plugins/leadsintel/whatsapp/claim/verify", { body: { company_id: companyId, code: code.trim() } })),
    onSuccess: () => { toast(t("verified"), "ok"); void qc.invalidateQueries({ queryKey: ["leadsintel-state"] }); },
    onError: (e) => { toast(e.message, "bad"); void qc.invalidateQueries({ queryKey: ["leadsintel-state"] }); },
  });
  const cancel = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/plugins/leadsintel/whatsapp/cancel", { body: { company_id: companyId } })),
    onSuccess: () => { setCancelling(false); void qc.invalidateQueries({ queryKey: ["leadsintel-state"] }); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); verify.mutate(); };
  return (
    <form onSubmit={submit} className="space-y-3">
      <p className="text-sm">{sentTo ? t("codeSentTo", { to: sentTo }) : t("codeSentPlain")}</p>
      <Field label={t("code")}><Input inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(digits(e.target.value))} maxLength={10} /></Field>
      <div className="flex gap-2">
        <Button type="submit" loading={verify.isPending} disabled={code.length < 4}>{t("verify")}</Button>
        <Button variant="ghost" onClick={() => setCancelling(true)}>{t("startAgain")}</Button>
      </div>
      <ConfirmDialog open={cancelling} onClose={() => setCancelling(false)} busy={cancel.isPending} title={t("startAgain")} confirmLabel={t("startAgain")}
        message={t("startAgainAsk")} onConfirm={() => cancel.mutate()} />
    </form>
  );
}

function Progress({ companyId, state }: { companyId: string; state: State }) {
  const { t } = useTranslation("leadsintel");
  const qc = useQueryClient();
  const [cancelling, setCancelling] = useState(false);
  // Lead Intel sets the number up with Meta, which takes a while: ask how it is going until it is connected or has failed.
  const poll = useQuery({
    queryKey: ["leadsintel-progress", companyId], refetchInterval: 5000,
    queryFn: async () => {
      const next = await unwrap(api.POST("/api/v1/plugins/leadsintel/whatsapp/refresh", { body: { company_id: companyId } }));
      qc.setQueryData(["leadsintel-state", companyId], next);
      return next;
    },
  });
  const cancel = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/plugins/leadsintel/whatsapp/cancel", { body: { company_id: companyId } })),
    onSuccess: () => { setCancelling(false); void qc.invalidateQueries({ queryKey: ["leadsintel-state"] }); },
  });
  const status = state.whatsapp?.status ?? "requested";
  return (
    <div className="space-y-3">
      <p className="flex items-center gap-2 text-sm"><Spinner className="h-4 w-4" />{t(`progress.${status}`, { defaultValue: t("progress.requested") })}</p>
      {poll.data?.warning && <Alert tone="warn">{poll.data.warning}</Alert>}
      {poll.error && <Alert tone="bad">{poll.error.message}</Alert>}
      {status === "awaiting_code" && <Alert>{t("awaitingCode")}</Alert>}
      <Button variant="ghost" onClick={() => setCancelling(true)}>{t("cancelSetup")}</Button>
      <ConfirmDialog open={cancelling} onClose={() => setCancelling(false)} busy={cancel.isPending} danger title={t("cancelSetup")} confirmLabel={t("cancelSetup")}
        message={t("cancelSetupAsk")} onConfirm={() => cancel.mutate()} />
    </div>
  );
}
