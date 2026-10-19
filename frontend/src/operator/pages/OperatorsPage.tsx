import { useQuery } from "@tanstack/react-query";
import { MoreHorizontal, UserPlus } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Alert, Badge, Button, Card, type Column, DataTable, Field, formatDate, Input, Menu, Modal, PageHeader, type Schemas, Select, StatusBadge, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../client";
import { ChangeConfirm } from "../components/ChangeConfirm";
import { SecretDialog } from "../components/SecretDialog";
import { TemporaryPasswordDialog } from "../components/TemporaryPasswordDialog";
import { useOperatorMe } from "../me";
import { useChange } from "../stepUp";
import { useRefreshOperator } from "./billing/invoiceDialogs";

type OperatorRow = Schemas["OperatorRow"];
type Line = Schemas["ActionLine"];
type Role = Schemas["OperatorCreateIn"]["role"];
const ROLES: NonNullable<Role>[] = ["superadmin", "billing", "support", "content", "readonly"];
const MIN_PASSWORD = 8;

export default function OperatorsPage() {
  const { t } = useTranslation("operator");
  const me = useOperatorMe();
  const refresh = useRefreshOperator();
  const [params] = useSearchParams();
  const [dialog, setDialog] = useState<
    | { kind: "add" }
    | { kind: "role" | "status" | "reset" | "resetPassword"; operator: OperatorRow }
    | null
  >(params.get("new") === "1" ? { kind: "add" } : null);
  const [secret, setSecret] = useState<Schemas["OperatorSecretOut"] | null>(null);
  const [temporary, setTemporary] = useState<{ name: string; password: string } | null>(null);
  const withCodes = me.data?.mfa_mode === "totp";
  const operators = useQuery({ queryKey: ["operator", "operators"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/operators")) });
  const actions = useQuery({ queryKey: ["operator", "actions"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/actions", { params: { query: { limit: 50 } } })) });
  const roles = useQuery({ queryKey: ["operator", "roles"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/roles")), staleTime: 300_000 });

  const staff: Column<OperatorRow>[] = [
    { header: t("operators.name"), sortValue: (o) => o.name, cell: (o) => <div><p className="font-medium">{o.name}{o.email === me.data?.email && <span className="ml-1.5 text-xs text-muted">({t("operators.you")})</span>}</p><p className="text-xs text-muted">{o.email}</p></div> },
    { header: t("operators.role"), cell: (o) => <Badge tone="brand">{t(`operators.roles.${o.role}`, o.role)}</Badge> },
    { header: t("operators.status"), cell: (o) => <div className="flex flex-wrap gap-1"><StatusBadge status={o.status} />{o.must_change_password && <Badge tone="warn">{t("operators.mustChange")}</Badge>}</div> },
    ...(withCodes ? [{ header: t("operators.mfa"), cell: (o: OperatorRow) => <Badge tone={o.mfa_enrolled ? "ok" : "bad"}>{t(o.mfa_enrolled ? "operators.mfaOn" : "operators.mfaOff")}</Badge> }] : []),
    { header: t("operators.sessions"), align: "right", hideBelow: "sm", cell: (o) => <span className="tnum text-sm">{o.open_sessions}</span> },
    { header: t("operators.lastSignIn"), hideBelow: "md", cell: (o) => <span className="text-sm">{o.last_sign_in_at ? formatDate(o.last_sign_in_at, true) : "-"}</span> },
    {
      header: "", align: "right",
      cell: (o) => o.email === me.data?.email ? null : (
        <Menu label={t("operators.actionsFor", { name: o.name })} trigger={<MoreHorizontal className="h-5 w-5 text-muted" />} items={[
          { label: t("operators.changeRole"), onSelect: () => setDialog({ kind: "role", operator: o }) },
          { label: t(o.status === "active" ? "operators.disable" : "operators.enable"), danger: o.status === "active", onSelect: () => setDialog({ kind: "status", operator: o }) },
          { label: t("operators.resetPassword"), onSelect: () => setDialog({ kind: "resetPassword", operator: o }) },
          ...(withCodes ? [{ label: t("operators.resetMfa"), onSelect: () => setDialog({ kind: "reset" as const, operator: o }) }] : []),
        ]} />
      ),
    },
  ];
  const trail: Column<Line>[] = [
    { header: t("operators.when"), cell: (l) => <span className="text-sm">{formatDate(l.occurred_at, true)}</span> },
    { header: t("operators.who"), hideBelow: "sm", cell: (l) => <span className="text-sm">{l.operator_name}</span> },
    { header: t("operators.action"), cell: (l) => <div><p className="font-mono text-xs">{l.action}</p><p className="text-xs text-muted">{l.target}</p></div> },
    { header: t("operators.outcome"), cell: (l) => <Badge tone={l.outcome === "ok" ? "ok" : l.outcome === "refused" ? "warn" : "bad"}>{l.outcome}</Badge> },
    { header: t("operators.reason"), hideBelow: "md", cell: (l) => <span className="text-xs text-muted">{l.reason ?? ""}</span> },
  ];

  return (
    <>
      <PageHeader title={t("operators.title")} description={t(withCodes ? "operators.descriptionCodes" : "operators.description")}
        actions={<Button onClick={() => setDialog({ kind: "add" })}><UserPlus className="h-4 w-4" /> {t("operators.add")}</Button>} />
      {me.data && !withCodes && <p className="mb-3 text-sm text-muted" data-testid="second-factor-state"><Badge tone="warn">{t("operators.secondFactorOff")}</Badge> {t("operators.secondFactorOffHint")}</p>}
      <DataTable rows={operators.data} columns={staff} rowKey={(o) => o.id} loading={operators.isPending} error={operators.isError ? operators.error.message : null}
        onRetry={() => void operators.refetch()} empty={{ title: t("operators.empty"), hint: t("operators.emptyHint") }} />

      <Card className="mt-6" title={t("operators.rolesTitle")} description={t("operators.rolesHint")}>
        {roles.isError ? <Alert tone="bad">{roles.error.message}</Alert> : (
          <dl className="grid gap-3 sm:grid-cols-2">
            {(roles.data?.roles ?? []).map((r) => (
              <div key={r.role}>
                <dt className="text-sm font-medium">{t(`operators.roles.${r.role}`, r.role)}</dt>
                <dd className="text-xs text-muted">{r.permissions.map((p) => t(`operators.perms.${p.replace(".", "_")}`, p)).join(" · ")}</dd>
              </div>
            ))}
          </dl>
        )}
      </Card>

      <h2 className="mb-2 mt-6 text-base font-semibold">{t("operators.trail")}</h2>
      <Card flush>
        <DataTable rows={actions.data} columns={trail} rowKey={(l) => String(l.id)} loading={actions.isPending} error={actions.isError ? actions.error.message : null}
          onRetry={() => void actions.refetch()} pageSize={15} dense empty={{ title: t("operators.trailEmpty"), hint: t("operators.trailEmptyHint") }} />
      </Card>

      {dialog?.kind === "add" && (
        <AddOperatorDialog onClose={() => setDialog(null)} withCodes={withCodes}
          onCreated={(name, made) => {
            if (made.temporary_password) setTemporary({ name, password: made.temporary_password });
            else if (made.mfa_secret && made.otpauth_uri) setSecret({ id: made.id, mfa_secret: made.mfa_secret, otpauth_uri: made.otpauth_uri });
            refresh();
          }} />
      )}
      {dialog?.kind === "role" && <RoleDialog operator={dialog.operator} onClose={() => setDialog(null)} />}
      {dialog?.kind === "status" && (
        <ChangeConfirm title={t(dialog.operator.status === "active" ? "operators.disableTitle" : "operators.enableTitle", { name: dialog.operator.name })}
          message={<p>{t(dialog.operator.status === "active" ? "operators.disableMessage" : "operators.enableMessage")}</p>}
          confirmLabel={t(dialog.operator.status === "active" ? "operators.disable" : "operators.enable")} danger={dialog.operator.status === "active"}
          run={() => opUnwrap(opApi.PATCH("/api/v1/operator/operators/{operator_id}", { params: { path: { operator_id: dialog.operator.id } }, body: { status: dialog.operator.status === "active" ? "disabled" : "active" } }))}
          onDone={() => { toast(t("operators.updated"), "ok"); refresh(); }} onClose={() => setDialog(null)} />
      )}
      {dialog?.kind === "reset" && (
        <ChangeConfirm title={t("operators.resetTitle", { name: dialog.operator.name })} message={<p>{t("operators.resetMessage")}</p>} confirmLabel={t("operators.resetMfa")} danger
          run={() => opUnwrap(opApi.POST("/api/v1/operator/operators/{operator_id}/reset-mfa", { params: { path: { operator_id: dialog.operator.id } } }))}
          onDone={(s) => { setSecret(s); refresh(); }} onClose={() => setDialog(null)} />
      )}
      {dialog?.kind === "resetPassword" && (
        <ChangeConfirm title={t("operators.resetPasswordTitle", { name: dialog.operator.name })} message={<p>{t("operators.resetPasswordMessage")}</p>} confirmLabel={t("operators.resetPassword")} danger
          run={() => opUnwrap(opApi.POST("/api/v1/operator/operators/{operator_id}/reset-password", { params: { path: { operator_id: dialog.operator.id } } }))}
          onDone={(made) => { setTemporary({ name: dialog.operator.name, password: made.temporary_password }); refresh(); }} onClose={() => setDialog(null)} />
      )}
      {secret && <SecretDialog secret={secret} onClose={() => setSecret(null)} />}
      {temporary && <TemporaryPasswordDialog name={temporary.name} password={temporary.password} onClose={() => setTemporary(null)} />}
    </>
  );
}

function AddOperatorDialog({ onClose, onCreated, withCodes }: { onClose: () => void; onCreated: (name: string, made: Schemas["OperatorCreatedOut"]) => void; withCodes: boolean }) {
  const { t } = useTranslation("operator");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<NonNullable<Role>>("readonly");
  const [problem, setProblem] = useState<string | null>(null);
  // Leaving the password empty makes a random temporary one; either way the person chooses their own at the first sign-in.
  const ready = name.trim().length >= 2 && /^\S+@\S+\.\S+$/.test(email.trim()) && (password === "" || password.length >= MIN_PASSWORD);
  const create = useChange(
    () => opUnwrap(opApi.POST("/api/v1/operator/operators", { body: { name: name.trim(), email: email.trim(), password: password || null, role } })),
    { onSuccess: (made) => { toast(t("operators.created"), "ok"); onCreated(name.trim(), made); onClose(); }, onError: (error) => setProblem(error.message) },
  );
  return (
    <Modal open onClose={onClose} title={t("operators.add")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="operator-form" loading={create.isPending} disabled={!ready}>{t("operators.create")}</Button></>}>
      <form id="operator-form" className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (ready && !create.isPending) { setProblem(null); create.mutate(undefined); } }}>
        <Field label={t("operators.fullName")} required><Input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} autoFocus /></Field>
        <Field label={t("operators.email")} required><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={200} autoComplete="off" /></Field>
        <Field label={t("operators.password")} hint={t("operators.passwordHint", { min: MIN_PASSWORD })} error={password && password.length < MIN_PASSWORD ? t("operators.passwordShort", { min: MIN_PASSWORD }) : null}>
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
        </Field>
        <Field label={t("operators.role")} hint={t(`operators.roleHints.${role}`)}>
          <Select value={role} onChange={(e) => setRole(e.target.value as NonNullable<Role>)}>{ROLES.map((r) => <option key={r} value={r}>{t(`operators.roles.${r}`)}</option>)}</Select>
        </Field>
        <Alert tone="info">{t(withCodes ? "operators.createNote" : "operators.createNotePassword")}</Alert>
        {problem && <Alert tone="bad">{problem}</Alert>}
      </form>
    </Modal>
  );
}

function RoleDialog({ operator, onClose }: { operator: OperatorRow; onClose: () => void }) {
  const { t } = useTranslation("operator");
  const refresh = useRefreshOperator();
  const [role, setRole] = useState<NonNullable<Role>>(operator.role as NonNullable<Role>);
  const [problem, setProblem] = useState<string | null>(null);
  const save = useChange(
    () => opUnwrap(opApi.PATCH("/api/v1/operator/operators/{operator_id}", { params: { path: { operator_id: operator.id } }, body: { role } })),
    { onSuccess: () => { toast(t("operators.updated"), "ok"); refresh(); onClose(); }, onError: (error) => setProblem(error.message) },
  );
  return (
    <Modal open onClose={onClose} title={t("operators.roleTitle", { name: operator.name })} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="role-form" loading={save.isPending} disabled={role === operator.role}>{t("operators.saveRole")}</Button></>}>
      <form id="role-form" className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (role !== operator.role && !save.isPending) { setProblem(null); save.mutate(undefined); } }}>
        <Field label={t("operators.role")} hint={t(`operators.roleHints.${role}`)}>
          <Select value={role} onChange={(e) => setRole(e.target.value as NonNullable<Role>)}>{ROLES.map((r) => <option key={r} value={r}>{t(`operators.roles.${r}`)}</option>)}</Select>
        </Field>
        {problem && <Alert tone="bad">{problem}</Alert>}
      </form>
    </Modal>
  );
}
