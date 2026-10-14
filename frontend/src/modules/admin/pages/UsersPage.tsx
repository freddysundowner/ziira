import { KeyRound, Plus, ShieldCheck, UserCheck, UserX } from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  api, ApiError, Button, ConfirmDialog, DataTable, Drawer, ErrorText, Field, FormGrid, Input, Menu, Modal, orNull, PageHeader, Select, StatusBadge, toast, unwrap,
  useCompany, useFormState, useMutation, useQuery, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

type User = Schemas["UserOut"];

export default function UsersPage() {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [rolesFor, setRolesFor] = useState<User | null>(null);
  const [passwordFor, setPasswordFor] = useState<User | null>(null);
  const [toggle, setToggle] = useState<User | null>(null);
  const users = useQuery({ queryKey: ["users"], queryFn: () => unwrap(api.GET("/api/v1/users")) });

  const setActive = useMutation({
    mutationFn: (u: User) => unwrap(api.POST("/api/v1/users/{user_id}/status", { params: { path: { user_id: u.id } }, body: { active: u.status === "disabled" } })),
    onSuccess: (u) => { void qc.invalidateQueries({ queryKey: ["users"] }); toast(t(u.status === "disabled" ? "disabledDone" : "enabledDone", { name: u.full_name }), "ok"); setToggle(null); },
  });

  return (
    <>
      <PageHeader title={t("users")} description={t("usersHint")} actions={<Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("newUser")}</Button>} />
      <DataTable
        rows={users.data} loading={users.isLoading} error={users.error?.message} onRetry={() => void users.refetch()} rowKey={(u) => u.id}
        searchText={(u) => `${u.full_name} ${u.email ?? ""} ${u.phone ?? ""}`} searchPlaceholder={t("searchUsers")} pageSize={20}
        empty={{ title: t("noUsers"), action: <Button onClick={() => setCreating(true)}>{t("newUser")}</Button> }}
        columns={[
          { header: t("fullName"), sortValue: (u) => u.full_name, cell: (u) => <span className="font-medium">{u.full_name}</span> },
          { header: t("email"), hideBelow: "md", sortValue: (u) => u.email, cell: (u) => u.email ?? "—" },
          { header: t("phone"), hideBelow: "lg", cell: (u) => u.phone ?? "—" },
          { header: t("status"), cell: (u) => <StatusBadge status={u.status} /> },
          {
            header: "", align: "right", cell: (u) => (
              <Menu label={t("actions")} trigger={<span className="rounded-lg px-2 py-1 text-muted hover:bg-sunken">•••</span>} items={[
                { label: t("manageRoles"), icon: <ShieldCheck className="h-4 w-4" />, onSelect: () => setRolesFor(u) },
                { label: t("setPassword"), icon: <KeyRound className="h-4 w-4" />, onSelect: () => setPasswordFor(u) },
                "separator",
                u.status === "disabled"
                  ? { label: t("enable"), icon: <UserCheck className="h-4 w-4" />, onSelect: () => setToggle(u) }
                  : { label: t("disable"), icon: <UserX className="h-4 w-4" />, danger: true, onSelect: () => setToggle(u) },
              ]} />
            ),
          },
        ]}
      />
      <NewUser open={creating} onClose={() => setCreating(false)} />
      <RolesDrawer user={rolesFor} onClose={() => setRolesFor(null)} />
      <PasswordModal user={passwordFor} onClose={() => setPasswordFor(null)} />
      <ConfirmDialog open={!!toggle} onClose={() => setToggle(null)} busy={setActive.isPending} danger={toggle?.status !== "disabled"}
        title={toggle?.status === "disabled" ? t("enable") : t("disable")} confirmLabel={toggle?.status === "disabled" ? t("enable") : t("disable")}
        message={toggle?.status === "disabled" ? t("enableAsk", { name: toggle?.full_name }) : t("disableAsk", { name: toggle?.full_name })}
        onConfirm={() => toggle && setActive.mutate(toggle)} />
    </>
  );
}

function NewUser({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const f = useFormState({ full_name: "", email: "", phone: "", password: "" });
  const create = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/users", { body: { full_name: f.values.full_name.trim(), email: orNull(f.values.email), phone: orNull(f.values.phone), password: orNull(f.values.password) } })),
    onSuccess: (u) => { void qc.invalidateQueries({ queryKey: ["users"] }); toast(t("created", { name: u.full_name }), "ok"); f.reset(); onClose(); },
    onError: f.fail,
  });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };
  return (
    <Drawer open={open} onClose={onClose} title={t("newUser")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="new-user" loading={create.isPending}>{t("save")}</Button></>}>
      <form id="new-user" onSubmit={submit} className="space-y-4">
        <Field label={t("fullName")} required error={f.error("full_name")}><Input {...f.bind("full_name")} required autoFocus /></Field>
        <FormGrid>
          <Field label={t("email")} error={f.error("email")}><Input type="email" {...f.bind("email")} /></Field>
          <Field label={t("phone")} error={f.error("phone")}><Input type="tel" {...f.bind("phone")} /></Field>
        </FormGrid>
        <Field label={t("password")} hint={t("passwordHint")} error={f.error("password")}><Input type="password" minLength={8} autoComplete="new-password" {...f.bind("password")} /></Field>
        <ErrorText>{create.error instanceof ApiError && Object.keys(create.error.fields).length === 0 ? create.error.message : null}</ErrorText>
      </form>
    </Drawer>
  );
}

function PasswordModal({ user, onClose }: { user: User | null; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const [password, setPassword] = useState("");
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/users/{user_id}/password", { params: { path: { user_id: user!.id } }, body: { password } })),
    onSuccess: () => { toast(t("passwordSet"), "ok"); setPassword(""); onClose(); },
  });
  return (
    <Modal open={!!user} onClose={onClose} title={`${t("setPassword")} · ${user?.full_name ?? ""}`} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button loading={save.isPending} disabled={password.length < 8} onClick={() => save.mutate()}>{t("save")}</Button></>}>
      <Field label={t("newPassword")} hint={t("passwordHint")}><Input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
    </Modal>
  );
}

function RolesDrawer({ user, onClose }: { user: User | null; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const { companies } = useCompany();
  const id = user?.id ?? "";
  const grants = useQuery({ enabled: !!user, queryKey: ["grants", id], queryFn: () => unwrap(api.GET("/api/v1/users/{user_id}/roles", { params: { path: { user_id: id } } })) });
  const roles = useQuery({ enabled: !!user, queryKey: ["roles"], queryFn: () => unwrap(api.GET("/api/v1/roles")) });
  const f = useFormState({ role_id: "", scope: "tenant", company_id: "", branch_id: "" });
  const refresh = () => qc.invalidateQueries({ queryKey: ["grants", id] });
  const grant = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/users/{user_id}/roles", { params: { path: { user_id: id } }, body: {
      role_id: f.values.role_id, scope: f.values.scope as "tenant", company_id: f.values.company_id || null, branch_id: f.values.branch_id || null } })),
    onSuccess: () => { void refresh(); toast(t("roleGranted"), "ok"); },
  });
  const revoke = useMutation({
    mutationFn: (grantId: string) => unwrap(api.DELETE("/api/v1/users/{user_id}/roles/{grant_id}", { params: { path: { user_id: id, grant_id: grantId } } })),
    onSuccess: () => { void refresh(); toast(t("roleRevoked"), "ok"); },
  });
  const company = companies.find((c) => c.id === f.values.company_id);
  const needCompany = f.values.scope === "company" || f.values.scope === "branch";

  return (
    <Drawer open={!!user} onClose={onClose} title={`${t("roles")} · ${user?.full_name ?? ""}`}>
      <div className="space-y-6">
        <section>
          <h3 className="mb-2 text-sm font-semibold">{t("currentRoles")}</h3>
          {grants.isLoading ? <p className="text-sm text-muted">…</p> : (grants.data ?? []).length === 0 ? <p className="text-sm text-muted">{t("noGrants")}</p> : (
            <ul className="divide-y divide-line rounded-xl border border-line">
              {(grants.data ?? []).map((g) => (
                <li key={g.id} className="flex items-center justify-between gap-3 px-3 py-2.5">
                  <div><p className="font-medium">{g.role_name}</p><p className="text-xs text-muted">{t(`scope.${g.scope}`)}{g.company_id ? ` · ${companies.find((c) => c.id === g.company_id)?.name ?? ""}` : ""}</p></div>
                  <Button variant="ghost" size="sm" loading={revoke.isPending && revoke.variables === g.id} onClick={() => revoke.mutate(g.id)}>{t("remove")}</Button>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="space-y-3 rounded-xl bg-sunken p-4">
          <h3 className="text-sm font-semibold">{t("addRole")}</h3>
          <Field label={t("role")}>
            <Select {...f.bind("role_id")}><option value="">{t("choose")}</option>{(roles.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</Select>
          </Field>
          <Field label={t("appliesTo")}>
            <Select {...f.bind("scope")}>{["tenant", "company", "branch", "own"].map((s) => <option key={s} value={s}>{t(`scope.${s}`)}</option>)}</Select>
          </Field>
          {needCompany && (
            <Field label={t("company")}>
              <Select value={f.values.company_id} onChange={(e) => { f.set("company_id", e.target.value); f.set("branch_id", ""); }}>
                <option value="">{t("choose")}</option>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </Field>
          )}
          {f.values.scope === "branch" && company && (
            <Field label={t("branch")}><Select {...f.bind("branch_id")}><option value="">{t("choose")}</option>{company.branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select></Field>
          )}
          <Button loading={grant.isPending} disabled={!f.values.role_id || (needCompany && !f.values.company_id) || (f.values.scope === "branch" && !f.values.branch_id)} onClick={() => grant.mutate()}>{t("grant")}</Button>
        </section>
      </div>
    </Drawer>
  );
}
