import { Building2, Pencil, Plus, Power, Store } from "lucide-react";
import { useState } from "react";

import {
  Alert, api, ApiError, Badge, Button, Card, ConfirmDialog, DataTable, EmptyState, Menu, PageHeader, toast, unwrap, useCan, useMutation, useQuery, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

import { BranchDrawer } from "./organisation/BranchDrawer";
import { CompanyDrawer } from "./organisation/CompanyDrawer";

type Company = Schemas["CompanySummary"];
type Branch = Schemas["BranchSummary"];

/** Companies and branches: add and edit them, close a branch that is no longer used (its history stays). */
export default function OrganisationPage() {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const organisation = useQuery({ queryKey: ["organisation"], queryFn: () => unwrap(api.GET("/api/v1/organisation")) });
  const [company, setCompany] = useState<Company | "new">();
  const [branch, setBranch] = useState<{ companyId: string; branch: Branch | null }>();
  const [closing, setClosing] = useState<Branch>();

  const refresh = () => { void qc.invalidateQueries({ queryKey: ["organisation"] }); void qc.invalidateQueries({ queryKey: ["companies"] }); };
  const close = useMutation({
    meta: { silent: true },
    mutationFn: (b: Branch) => unwrap(api.POST("/api/v1/branches/{branch_id}/deactivate", { params: { path: { branch_id: b.id } } })),
    onSuccess: (b) => { refresh(); toast(t("org.branchClosed", { name: b.name }), "ok"); setClosing(undefined); },
  });
  const reopen = useMutation({
    mutationFn: (b: Branch) => unwrap(api.POST("/api/v1/branches/{branch_id}/reactivate", { params: { path: { branch_id: b.id } } })),
    onSuccess: (b) => { refresh(); toast(t("org.branchReopened", { name: b.name }), "ok"); },
  });
  const manageAll = useCan("organisation.manage");

  const list = organisation.data ?? [];
  return (
    <>
      <PageHeader title={t("org.title")} description={t("org.hint")}
        actions={manageAll ? <Button onClick={() => setCompany("new")}><Plus className="h-4 w-4" />{t("org.addCompany")}</Button> : undefined} />
      {organisation.error ? <Alert tone="bad">{organisation.error.message} <button className="underline" onClick={() => void organisation.refetch()}>{t("org.retry")}</button></Alert> : null}
      {organisation.isLoading ? <p className="text-sm text-muted">…</p> : null}
      {!organisation.isLoading && !organisation.error && list.length === 0 && <EmptyState title={t("org.none")} hint={t("org.noneHint")} icon={<Building2 className="h-6 w-6" />} />}
      <div className="space-y-6">
        {list.map((c) => (
          <Card key={c.id} flush
            title={<span className="flex flex-wrap items-center gap-2"><Building2 className="h-4 w-4 text-muted" />{c.name}<Badge>{c.currency}</Badge>{c.country ? <Badge>{c.country}</Badge> : null}</span>}
            description={[c.tax_id ? t("org.taxLine", { id: c.tax_id }) : null, c.vat_registered ? t("org.taxRegistered") : null, c.timezone].filter(Boolean).join(" · ")}
            actions={<>
              <Button variant="secondary" size="sm" onClick={() => setCompany(c)}><Pencil className="h-4 w-4" />{t("org.editCompany")}</Button>
              <Button size="sm" onClick={() => setBranch({ companyId: c.id, branch: null })}><Plus className="h-4 w-4" />{t("org.addBranch")}</Button>
            </>}>
            <DataTable
              rows={c.branches} rowKey={(b) => b.id} pageSize={20} searchText={(b) => `${b.code} ${b.name} ${b.address ?? ""}`}
              empty={{ title: t("org.noBranches"), action: <Button onClick={() => setBranch({ companyId: c.id, branch: null })}>{t("org.addBranch")}</Button> }}
              columns={[
                { header: t("org.branchCode"), sortValue: (b) => b.code, cell: (b) => <span className="font-medium">{b.code}</span> },
                { header: t("org.branchName"), sortValue: (b) => b.name, cell: (b) => <span className="flex items-center gap-2"><Store className="h-4 w-4 text-muted" />{b.name}</span> },
                { header: t("org.address"), hideBelow: "lg", cell: (b) => b.address ?? "—" },
                { header: t("org.users"), hideBelow: "md", align: "right", cell: (b) => b.counts.users ?? 0 },
                { header: t("org.devices"), hideBelow: "md", align: "right", cell: (b) => b.counts.devices ?? 0 },
                { header: t("org.locations"), hideBelow: "md", align: "right", cell: (b) => b.counts.locations ?? 0 },
                { header: t("status"), cell: (b) => <Badge tone={b.is_active ? "ok" : "neutral"}>{t(b.is_active ? "org.open" : "org.closed")}</Badge> },
                {
                  header: "", align: "right", cell: (b) => (
                    <Menu label={t("actions")} trigger={<span className="rounded-lg px-2 py-1 text-muted hover:bg-sunken">•••</span>} items={[
                      { label: t("edit"), icon: <Pencil className="h-4 w-4" />, onSelect: () => setBranch({ companyId: c.id, branch: b }) },
                      b.is_active
                        ? { label: t("org.closeBranch"), icon: <Power className="h-4 w-4" />, danger: true, onSelect: () => { close.reset(); setClosing(b); } }
                        : { label: t("org.reopenBranch"), icon: <Power className="h-4 w-4" />, onSelect: () => reopen.mutate(b) },
                    ]} />
                  ),
                },
              ]}
            />
          </Card>
        ))}
      </div>
      {company !== undefined && <CompanyDrawer key={company === "new" ? "new" : company.id} company={company === "new" ? null : company} onClose={() => setCompany(undefined)} />}
      {branch && <BranchDrawer key={branch.branch?.id ?? "new"} companyId={branch.companyId} branch={branch.branch} onClose={() => setBranch(undefined)} />}
      <ConfirmDialog open={!!closing} onClose={() => setClosing(undefined)} busy={close.isPending} danger title={t("org.closeBranch")} confirmLabel={t("org.closeBranch")}
        message={<div className="space-y-3"><p>{t("org.closeAsk", { name: closing?.name })}</p>{close.error instanceof ApiError ? <Alert tone="bad">{close.error.message}</Alert> : null}</div>}
        onConfirm={() => closing && close.mutate(closing)} />
    </>
  );
}
