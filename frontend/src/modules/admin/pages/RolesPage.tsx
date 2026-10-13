import { api, Card, PageHeader, Table, useQuery, useTranslation } from "@/sdk";

export default function RolesPage() {
  const { t } = useTranslation("kernel");
  const roles = useQuery({ queryKey: ["roles"], queryFn: async () => (await api.GET("/api/v1/roles")).data ?? [] });
  return (
    <>
      <PageHeader title={t("roles")} />
      <Card>
        <Table
          rows={roles.data ?? []}
          rowKey={(r) => r.id}
          empty={t("noRoles")}
          columns={[
            { header: t("role"), cell: (r) => (r.is_system ? `${r.name} · ${t("system")}` : r.name) },
            { header: t("permissions"), cell: (r) => <span className="text-xs text-slate-600">{r.permissions.join(", ") || "—"}</span> },
          ]}
        />
      </Card>
    </>
  );
}
