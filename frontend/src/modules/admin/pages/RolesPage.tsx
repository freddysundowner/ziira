import { Plus } from "lucide-react";
import { useMemo, useState } from "react";

import {
  api, Badge, Button, Checkbox, DataTable, Drawer, Field, Input, PageHeader, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

type Role = Schemas["RoleOut"];

export default function RolesPage() {
  const { t } = useTranslation("kernel");
  const [editing, setEditing] = useState<Role | "new" | null>(null);
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => unwrap(api.GET("/api/v1/roles")) });
  return (
    <>
      <PageHeader title={t("roles")} description={t("rolesHint")} actions={<Button onClick={() => setEditing("new")}><Plus className="h-4 w-4" />{t("newRole")}</Button>} />
      <DataTable rows={roles.data} loading={roles.isLoading} error={roles.error?.message} onRetry={() => void roles.refetch()} rowKey={(r) => r.id}
        empty={{ title: t("noRoles") }}
        columns={[
          { header: t("role"), sortValue: (r) => r.name, cell: (r) => <span className="flex items-center gap-2 font-medium">{r.name}{r.is_system && <Badge tone="info">{t("system")}</Badge>}</span> },
          { header: t("permissions"), cell: (r) => <span className="text-muted">{t("permissionCount", { count: r.permissions.length })}</span> },
          { header: "", align: "right", cell: (r) => <Button variant="secondary" size="sm" onClick={() => setEditing(r)}>{r.is_system ? t("view") : t("edit")}</Button> },
        ]} />
      <RoleEditor target={editing} onClose={() => setEditing(null)} />
    </>
  );
}

function RoleEditor({ target, onClose }: { target: Role | "new" | null; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const role = target && target !== "new" ? target : null;
  const permissions = useQuery({ enabled: !!target, queryKey: ["permissions"], queryFn: () => unwrap(api.GET("/api/v1/permissions")) });
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const [seen, setSeen] = useState<unknown>(null);
  if (seen !== target) { setSeen(target); setName(role?.name ?? ""); setPicked(new Set(role?.permissions ?? [])); }
  const current = picked ?? new Set<string>();
  const readOnly = !!role?.is_system;

  const byUnit = useMemo(() => {
    const out = new Map<string, Schemas["PermissionOut"][]>();
    for (const p of permissions.data ?? []) out.set(p.unit_name, [...(out.get(p.unit_name) ?? []), p]);
    return [...out.entries()];
  }, [permissions.data]);

  const save = useMutation({
    mutationFn: async () => {
      const list = [...current];
      if (role) return unwrap(api.PUT("/api/v1/roles/{role_id}/permissions", { params: { path: { role_id: role.id } }, body: { permissions: list } }));
      return unwrap(api.POST("/api/v1/roles", { body: { name: name.trim(), permissions: list } }));
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["roles"] }); toast(t("roleSaved"), "ok"); onClose(); },
  });
  const flip = (code: string) => setPicked((s) => { const n = new Set(s); if (n.has(code)) n.delete(code); else n.add(code); return n; });

  return (
    <Drawer open={!!target} onClose={onClose} title={role ? role.name : t("newRole")}
      footer={readOnly ? <Button variant="secondary" onClick={onClose}>{t("close")}</Button> : <><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button loading={save.isPending} disabled={!role && !name.trim()} onClick={() => save.mutate()}>{t("save")}</Button></>}>
      <div className="space-y-5">
        {!role && <Field label={t("roleName")} required><Input value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field>}
        {readOnly && <p className="rounded-lg bg-info-soft px-3 py-2 text-sm text-info">{t("systemRole")}</p>}
        {byUnit.map(([unit, list]) => {
          const chosen = list.filter((p) => current.has(p.code)).length;
          return (
            <details key={unit} className="group rounded-xl border border-line">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-3 py-2.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
                <span className="text-sm font-semibold capitalize">{unit}</span>
                <span className="text-xs text-muted">{t("permissionsOf", { chosen, total: list.length })}<span aria-hidden className="ml-1 inline-block transition-transform group-open:rotate-90">›</span></span>
              </summary>
              <div className="space-y-1.5 border-t border-line p-3">
                {!readOnly && (
                  <button type="button" className="mb-1 text-xs font-medium text-brand-strong hover:underline"
                    onClick={() => setPicked((s) => { const n = new Set(s); const all = list.every((p) => n.has(p.code)); list.forEach((p) => (all ? n.delete(p.code) : n.add(p.code))); return n; })}>
                    {t("toggleAll")}</button>
                )}
                {list.map((p) => (
                  <div key={p.code} className="flex items-start gap-2">
                    <Checkbox label={<span><span className="font-medium">{p.code}</span><span className="block text-xs text-muted">{p.description}</span></span>} checked={current.has(p.code)} disabled={readOnly} onChange={() => flip(p.code)} />
                  </div>
                ))}
              </div>
            </details>
          );
        })}
      </div>
    </Drawer>
  );
}
