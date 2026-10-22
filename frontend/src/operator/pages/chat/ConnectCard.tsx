import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Alert, Badge, Button, Card, Field, Input, Modal, Spinner, Tabs, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { useChange } from "../../stepUp";
import { canSendNumber, type ChatOverview, connectionStateKey, digits, isOpen } from "./logic";

type Mode = "new" | "existing";

/** Step 2: connect the number. A new one, one already at the provider (claimed with a code), or one to recover. */
export function ConnectCard({ overview: o, editable, onChanged }: { overview: ChatOverview; editable: boolean; onChanged: () => void }) {
  const { t } = useTranslation("operator");
  const c = o.connection;
  const open = isOpen(c.state);
  const [mode, setMode] = useState<Mode>("new");
  const [form, setForm] = useState({ country: "", phone: "", business: "", display: "" });
  const [code, setCode] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const set = (key: keyof typeof form, value: string) => { setForm({ ...form, [key]: value }); setProblem(null); };

  const poll = useQuery({
    queryKey: ["operator", "chat", "poll", c.state],
    queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/chat/connect/status")),
    enabled: open && editable,
    refetchInterval: 3000,
  });
  useEffect(() => {
    if (poll.data && poll.data.state !== c.state) onChanged();
  }, [poll.data, c.state, onChanged]);

  const start = useChange(
    () => opUnwrap(opApi.POST("/api/v1/operator/chat/connect", { body: { mode, country_code: digits(form.country), phone_number: digits(form.phone), business_name: form.business.trim(), display_name: form.display.trim() } })),
    { onSuccess: () => { setProblem(null); onChanged(); }, onError: (e) => setProblem(e.message) },
  );
  const cancel = useChange(() => opUnwrap(opApi.POST("/api/v1/operator/chat/connect/cancel")), { onSuccess: onChanged, onError: (e) => setProblem(e.message) });
  const sendCode = useChange(() => opUnwrap(opApi.POST("/api/v1/operator/chat/connect/code", { body: { code: digits(code) } })), {
    onSuccess: () => { setCode(""); setProblem(null); onChanged(); }, onError: (e) => setProblem(e.message),
  });
  const ready = canSendNumber(mode, form);

  return (
    <Card title={t("chat.connect.title")} description={t("chat.connect.intro")}
      actions={<Badge tone={c.state === "connected" ? "ok" : c.state === "failed" ? "bad" : open ? "warn" : "neutral"}>{t(`chat.connect.states.${connectionStateKey(c.state)}`)}</Badge>}>
      {c.state === "connected" && (
        <div className="space-y-3">
          <p className="text-sm"><span className="text-muted">{t("chat.connect.number")}</span> <span className="font-medium tnum" data-testid="connected-number">{c.display_phone ?? c.number}</span></p>
          {editable && <div className="flex justify-end"><Button variant="danger" size="sm" onClick={() => setConfirmOpen(true)}>{t("chat.connect.disconnect")}</Button></div>}
          <DisconnectDialog open={confirmOpen} number={c.number ?? ""} onClose={() => setConfirmOpen(false)} onDone={() => { setConfirmOpen(false); toast(t("chat.connect.disconnected"), "ok"); onChanged(); }} />
        </div>
      )}

      {open && (
        <div className="space-y-3" aria-live="polite">
          <p className="flex items-center gap-2 text-sm"><Spinner /> <span data-testid="connect-progress">{t(`chat.connect.progress.${c.state}`)}</span></p>
          {c.message && <p className="text-sm text-muted">{c.message}</p>}
          {poll.isError && <Alert tone="warn">{(poll.error as Error).message}</Alert>}
          {editable && c.mode === "existing" && (
            <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (digits(code).length >= 4 && !sendCode.isPending) sendCode.mutate(undefined); }}>
              <Field label={t("chat.connect.codeLabel")} hint={t("chat.connect.codeHint")} className="min-w-48">
                <Input value={code} inputMode="numeric" autoComplete="one-time-code" maxLength={8} placeholder="123456" className="font-mono tracking-widest"
                  onChange={(e) => { setCode(digits(e.target.value)); setProblem(null); }} />
              </Field>
              <Button type="submit" size="sm" loading={sendCode.isPending} disabled={digits(code).length < 4}>{t("chat.connect.sendCode")}</Button>
            </form>
          )}
          {problem && <Alert tone="bad">{problem}</Alert>}
          {editable && <div className="flex justify-end"><Button variant="secondary" size="sm" loading={cancel.isPending} onClick={() => cancel.mutate(undefined)}>{t("chat.connect.cancel")}</Button></div>}
        </div>
      )}

      {!open && c.state !== "connected" && (
        <div className="space-y-4">
          {(c.state === "failed" || c.state === "cancelled") && (
            <Alert tone={c.state === "failed" ? "bad" : "info"}>{c.state === "failed" ? (c.message || t("chat.connect.failedFallback")) : t("chat.connect.cancelled")}</Alert>
          )}
          <Tabs<Mode> tabs={[{ id: "new", label: t("chat.connect.modes.new") }, { id: "existing", label: t("chat.connect.modes.existing") }]} value={mode} onChange={(m) => { setMode(m); setProblem(null); }} />
          <p className="text-sm text-muted">{t(`chat.connect.modeHints.${mode}`)}</p>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (ready && editable && !start.isPending) start.mutate(undefined); }}>
            <fieldset disabled={!editable} className="grid gap-3 sm:grid-cols-4">
              <Field label={t("chat.connect.country")} hint={t("chat.connect.countryHint")} required>
                <Input value={form.country} inputMode="numeric" maxLength={5} placeholder="44" onChange={(e) => set("country", digits(e.target.value))} />
              </Field>
              <Field label={t("chat.connect.phone")} hint={t("chat.connect.phoneHint")} required className="sm:col-span-3">
                <Input value={form.phone} inputMode="numeric" maxLength={20} onChange={(e) => set("phone", digits(e.target.value))} />
              </Field>
              {mode === "new" && (
                <>
                  <Field label={t("chat.connect.business")} hint={t("chat.connect.businessHint")} required className="sm:col-span-2">
                    <Input value={form.business} maxLength={100} onChange={(e) => set("business", e.target.value)} />
                  </Field>
                  <Field label={t("chat.connect.display")} hint={t("chat.connect.displayHint")} required className="sm:col-span-2">
                    <Input value={form.display} maxLength={100} onChange={(e) => set("display", e.target.value)} />
                  </Field>
                </>
              )}
            </fieldset>
            {mode === "new" && <p className="text-xs text-muted">{t("chat.connect.metaNote")}</p>}
            {problem && <Alert tone="bad">{problem}</Alert>}
            {!o.key.is_set && <Alert tone="info">{t("chat.connect.needKey")}</Alert>}
            {editable && <div className="flex justify-end"><Button type="submit" size="sm" loading={start.isPending} disabled={!ready || !o.key.is_set}>{t(`chat.connect.start.${mode}`)}</Button></div>}
          </form>
          {editable && <FindExisting disabled={!o.key.is_set} onAdopted={onChanged} />}
        </div>
      )}
    </Card>
  );
}

/** Recovery: look a number up at the provider and, when it is already connected there, take it over. */
function FindExisting({ disabled, onAdopted }: { disabled: boolean; onAdopted: () => void }) {
  const { t } = useTranslation("operator");
  const [shown, setShown] = useState(false);
  const [country, setCountry] = useState("");
  const [phone, setPhone] = useState("");
  const [found, setFound] = useState<{ found: boolean; active: boolean; display_phone: string | null } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const body = { country_code: digits(country), phone_number: digits(phone) };
  const look = useChange(() => opUnwrap(opApi.POST("/api/v1/operator/chat/lookup", { body })), { onSuccess: setFound, onError: (e) => setProblem(e.message) });
  const adopt = useChange(() => opUnwrap(opApi.POST("/api/v1/operator/chat/adopt", { body })), {
    onSuccess: () => { toast(t("chat.find.adopted"), "ok"); onAdopted(); }, onError: (e) => setProblem(e.message),
  });
  if (!shown) return <button type="button" className="text-sm text-brand underline" onClick={() => setShown(true)}>{t("chat.find.open")}</button>;
  const valid = body.country_code.length >= 1 && body.phone_number.length >= 5;
  return (
    <div className="space-y-3 rounded-lg border border-line p-3">
      <p className="text-sm font-medium">{t("chat.find.title")}</p>
      <p className="text-sm text-muted">{t("chat.find.intro")}</p>
      <div className="grid gap-3 sm:grid-cols-4">
        <Field label={t("chat.connect.country")}><Input value={country} inputMode="numeric" maxLength={5} onChange={(e) => { setCountry(digits(e.target.value)); setFound(null); }} /></Field>
        <Field label={t("chat.connect.phone")} className="sm:col-span-3"><Input value={phone} inputMode="numeric" maxLength={20} onChange={(e) => { setPhone(digits(e.target.value)); setFound(null); }} /></Field>
      </div>
      {problem && <Alert tone="bad">{problem}</Alert>}
      {found && (found.found && found.active
        ? <Alert tone="ok">{t("chat.find.foundActive", { number: found.display_phone ?? "" })}</Alert>
        : <Alert tone="info">{found.found ? t("chat.find.foundInactive") : t("chat.find.notFound")}</Alert>)}
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="secondary" size="sm" loading={look.isPending} disabled={disabled || !valid} onClick={() => { setProblem(null); look.mutate(undefined); }}>{t("chat.find.look")}</Button>
        {found?.found && found.active && <Button type="button" size="sm" loading={adopt.isPending} onClick={() => { setProblem(null); adopt.mutate(undefined); }}>{t("chat.find.adopt")}</Button>}
      </div>
    </div>
  );
}

/** Disconnecting removes the number at the provider, so the number must be typed. */
function DisconnectDialog({ open, number, onClose, onDone }: { open: boolean; number: string; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation("operator");
  const [typed, setTyped] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const go = useChange(() => opUnwrap(opApi.POST("/api/v1/operator/chat/disconnect", { body: { confirm: typed } })), {
    onSuccess: () => { setTyped(""); onDone(); }, onError: (e) => setProblem(e.message),
  });
  const matches = digits(typed) === digits(number) && digits(number) !== "";
  return (
    <Modal open={open} onClose={onClose} title={t("chat.connect.disconnectTitle")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button variant="danger" loading={go.isPending} disabled={!matches} onClick={() => go.mutate(undefined)}>{t("chat.connect.disconnect")}</Button></>}>
      <div className="space-y-3">
        <p className="text-sm">{t("chat.connect.disconnectText", { number })}</p>
        <Field label={t("chat.connect.typeNumber")}><Input value={typed} onChange={(e) => { setTyped(e.target.value); setProblem(null); }} autoFocus /></Field>
        {problem && <Alert tone="bad">{problem}</Alert>}
      </div>
    </Modal>
  );
}
