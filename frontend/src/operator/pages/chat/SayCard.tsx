import { useState } from "react";

import { Alert, Button, Card, Field, Input, Select, Textarea, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { useChange } from "../../stepUp";
import type { ChatOverview } from "./logic";

type Texts = ChatOverview["bot"]["texts"];

/** What the bot says: welcome, hand-off and off-hours texts, the default language, opening hours, and the number's public profile. */
export function SayCard({ overview: o, editable, onChanged }: { overview: ChatOverview; editable: boolean; onChanged: () => void }) {
  const { t } = useTranslation("operator");
  const saved = o.bot.texts;
  const [draft, setDraft] = useState<Texts>(saved);
  const [problem, setProblem] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  const set = <K extends keyof Texts>(key: K, value: Texts[K]) => { setDraft({ ...draft, [key]: value }); setProblem(null); };
  const setProfile = (key: keyof Texts["profile"], value: string) => set("profile", { ...draft.profile, [key]: value });
  const save = useChange(() => opUnwrap(opApi.PUT("/api/v1/operator/chat/texts", { body: draft })), {
    onSuccess: (r) => { setWarning(r.profile_warning ?? null); toast(t("chat.say.saved"), "ok"); onChanged(); },
    onError: (e) => setProblem(e.message),
  });
  return (
    <Card title={t("chat.say.title")} description={t("chat.say.intro")}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (dirty && editable && !save.isPending) save.mutate(undefined); }}>
        <fieldset disabled={!editable} className="grid gap-3 sm:grid-cols-2">
          <Field label={t("chat.say.welcome")} hint={t("chat.say.welcomeHint")} className="sm:col-span-2">
            <Textarea rows={3} maxLength={600} value={draft.welcome} onChange={(e) => set("welcome", e.target.value)} />
          </Field>
          <Field label={t("chat.say.handoff")} hint={t("chat.say.handoffHint")}>
            <Textarea rows={3} maxLength={400} value={draft.handoff} onChange={(e) => set("handoff", e.target.value)} />
          </Field>
          <Field label={t("chat.say.offHours")} hint={t("chat.say.offHoursHint")}>
            <Textarea rows={3} maxLength={400} value={draft.off_hours} onChange={(e) => set("off_hours", e.target.value)} />
          </Field>
          <Field label={t("chat.say.language")} hint={t("chat.say.languageHint")}>
            <Select value={draft.language} onChange={(e) => set("language", e.target.value)}>
              <option value="auto">{t("chat.say.languages.auto")}</option>
              <option value="en">{t("chat.say.languages.en")}</option>
              <option value="sw">{t("chat.say.languages.sw")}</option>
            </Select>
          </Field>
          <div className="grid grid-cols-3 gap-2">
            <Field label={t("chat.say.hoursStart")}><Input type="time" value={draft.hours_start} onChange={(e) => set("hours_start", e.target.value)} /></Field>
            <Field label={t("chat.say.hoursEnd")}><Input type="time" value={draft.hours_end} onChange={(e) => set("hours_end", e.target.value)} /></Field>
            <Field label={t("chat.say.hoursZone")}><Input value={draft.hours_timezone} maxLength={60} onChange={(e) => set("hours_timezone", e.target.value)} /></Field>
          </div>
          <p className="text-xs text-muted sm:col-span-2">{t("chat.say.hoursHint")}</p>
          <p className="text-sm font-medium sm:col-span-2">{t("chat.say.profile")}</p>
          <Field label={t("chat.say.about")} hint={t("chat.say.aboutHint")} className="sm:col-span-2">
            <Input maxLength={139} value={draft.profile.about} onChange={(e) => setProfile("about", e.target.value)} />
          </Field>
          <Field label={t("chat.say.description")} className="sm:col-span-2">
            <Textarea rows={2} maxLength={512} value={draft.profile.description} onChange={(e) => setProfile("description", e.target.value)} />
          </Field>
          <Field label={t("chat.say.website")} className="sm:col-span-2">
            <Input type="url" maxLength={200} value={draft.profile.website} onChange={(e) => setProfile("website", e.target.value)} />
          </Field>
        </fieldset>
        {problem && <Alert tone="bad">{problem}</Alert>}
        {warning && <Alert tone="warn">{t("chat.say.profileWarning", { reason: warning })}</Alert>}
        {editable && <div className="flex justify-end"><Button type="submit" size="sm" loading={save.isPending} disabled={!dirty}>{t("chat.say.save")}</Button></div>}
      </form>
    </Card>
  );
}
