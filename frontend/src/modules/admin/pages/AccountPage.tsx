import { Laptop, LogOut } from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  api, Alert, Badge, Button, Card, ConfirmDialog, DetailList, ErrorState, Field, formatDate, Input, LANGUAGES, PageHeader, Select, setLanguage, SkeletonRows,
  toast, type Theme, unwrap, useFormState, useMutation, useQuery, useQueryClient, useSession, useTheme, useTranslation, type Schemas,
} from "@/sdk";

import NotificationSettingsCard from "./account/NotificationSettingsCard";
import TwoStepCard from "./TwoStepCard";

type SessionRow = Schemas["SessionOut"];

/** The signed-in person's own settings: profile, password, devices, language and theme. Any user may open it. */
export default function AccountPage() {
  const { t } = useTranslation("kernel");
  const { me } = useSession();
  return (
    <>
      <PageHeader title={t("myAccount")} description={t("myAccountHint")} />
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <Card title={t("profile")}>
            <DetailList items={[{ label: t("fullName"), value: me?.full_name }, { label: t("email"), value: me?.email }, { label: t("roles"), value: (me?.roles ?? []).map((r) => r.role_name).join(", ") || null }]} />
          </Card>
          <Preferences />
          <NotificationSettingsCard />
          <PasswordCard />
          <TwoStepCard />
        </div>
        <Sessions />
      </div>
    </>
  );
}

function Preferences() {
  const { t, i18n } = useTranslation("kernel");
  const [theme, setTheme] = useTheme();
  return (
    <Card title={t("preferences")} description={t("preferencesHint")}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("language")}>
          <Select value={i18n.language} onChange={(e) => setLanguage(e.target.value as keyof typeof LANGUAGES)}>
            {Object.entries(LANGUAGES).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
          </Select>
        </Field>
        <Field label={t("theme")}>
          <Select value={theme} onChange={(e) => setTheme(e.target.value as Theme)}>
            {(["system", "light", "dark"] as const).map((v) => <option key={v} value={v}>{t(`themeName.${v}`)}</option>)}
          </Select>
        </Field>
      </div>
    </Card>
  );
}

function PasswordCard() {
  const { t } = useTranslation("kernel");
  const { signOut } = useSession();
  const f = useFormState({ current_password: "", new_password: "", confirm: "" });
  const change = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/auth/password", { body: { current_password: f.values.current_password, new_password: f.values.new_password } })),
    onSuccess: () => { toast(t("passwordChanged"), "ok"); f.reset(); void signOut(); },
    onError: (e) => { f.fail(e); toast(e.message, "bad"); },
  });
  const mismatch = f.values.confirm !== "" && f.values.confirm !== f.values.new_password;
  const submit = (e: FormEvent) => { e.preventDefault(); if (!mismatch) change.mutate(); };
  return (
    <Card title={t("changePassword")} description={t("changePasswordHint")}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t("currentPassword")} error={f.error("current_password")}><Input type="password" autoComplete="current-password" required {...f.bind("current_password")} /></Field>
        <Field label={t("newPassword")} hint={t("passwordHint")} error={f.error("new_password")}><Input type="password" autoComplete="new-password" minLength={8} required {...f.bind("new_password")} /></Field>
        <Field label={t("confirmPassword")} error={mismatch ? t("passwordsDiffer") : null}><Input type="password" autoComplete="new-password" required {...f.bind("confirm")} /></Field>
        <Button type="submit" loading={change.isPending} disabled={mismatch || f.values.new_password.length < 8}>{t("changePassword")}</Button>
      </form>
    </Card>
  );
}

function Sessions() {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [ending, setEnding] = useState<SessionRow | "others" | null>(null);
  const sessions = useQuery({ queryKey: ["my-sessions"], queryFn: () => unwrap(api.GET("/api/v1/auth/sessions")) });
  const others = (sessions.data ?? []).filter((s) => !s.current);
  const end = useMutation({
    mutationFn: async (target: SessionRow | "others") => {
      const list = target === "others" ? others : [target];
      for (const s of list) await unwrap(api.DELETE("/api/v1/auth/sessions/{session_id}", { params: { path: { session_id: s.id } } }));
    },
    onSuccess: () => { toast(t("signedOutDone"), "ok"); setEnding(null); },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["my-sessions"] }),
  });
  return (
    <Card title={t("devices")} description={t("devicesHint")}
      actions={others.length > 0 ? <Button size="sm" variant="secondary" onClick={() => setEnding("others")}><LogOut className="h-4 w-4" />{t("signOutOthers")}</Button> : undefined} flush>
      {sessions.error ? <ErrorState message={sessions.error.message} onRetry={() => void sessions.refetch()} /> : !sessions.data ? <SkeletonRows rows={3} cols={2} /> : (
        <ul className="divide-y divide-line">
          {sessions.data.map((s) => (
            <li key={s.id} className="flex items-center gap-3 px-4 py-3">
              <Laptop className="h-5 w-5 shrink-0 text-muted" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{s.device_name || t("unnamedDevice")} {s.current && <Badge tone="ok">{t("thisDevice")}</Badge>}</p>
                <p className="text-xs text-muted">{s.channel} · {t("lastUsed")} {formatDate(s.last_used_at, true)}</p>
              </div>
              {!s.current && <Button size="sm" variant="ghost" onClick={() => setEnding(s)}>{t("signOut")}</Button>}
            </li>
          ))}
        </ul>
      )}
      {sessions.data && others.length === 0 && <div className="px-4 pb-4"><Alert>{t("noOtherDevices")}</Alert></div>}
      <ConfirmDialog open={!!ending} onClose={() => setEnding(null)} busy={end.isPending} danger title={t("signOut")} confirmLabel={t("signOut")}
        message={ending === "others" ? t("signOutOthersAsk") : t("signOutDeviceAsk", { name: (ending as SessionRow | null)?.device_name || t("unnamedDevice") })}
        onConfirm={() => ending && end.mutate(ending)} />
    </Card>
  );
}
