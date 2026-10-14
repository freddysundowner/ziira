import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  api, Badge, Button, DataTable, Drawer, Field, Input, PageHeader, Select, StatusBadge, toast, unwrap, useCan, useFormState, useMutation, useQueryClient, useTranslation,
} from "@/sdk";

import { CompanyField, useFormCompany, useLocations } from "../lookups";

const KINDS = ["store", "warehouse", "transit", "virtual"] as const;
type Kind = (typeof KINDS)[number];

/** Places stock is kept: stores, warehouses, in-transit and virtual locations. */
export default function LocationsPage() {
  const { t } = useTranslation("inventory");
  const canManage = useCan("locations.manage");
  const [creating, setCreating] = useState(false);
  const locations = useLocations();
  const { companies } = useFormCompany("");
  const branchName = (id: string | null) => companies.flatMap((c) => c.branches).find((b) => b.id === id)?.name ?? "—";

  return (
    <>
      <PageHeader title={t("locations")} description={t("locationsHint")}
        actions={canManage && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("newLocation")}</Button>} />
      <DataTable
        rows={locations.data} loading={locations.isLoading} error={locations.error?.message} onRetry={() => void locations.refetch()} rowKey={(l) => l.id}
        searchText={(l) => `${l.code} ${l.name}`} searchPlaceholder={t("searchLocations")}
        empty={{ title: t("noLocations"), hint: t("noLocationsHint"), action: canManage ? <Button onClick={() => setCreating(true)}>{t("newLocation")}</Button> : undefined }}
        columns={[
          { header: t("code"), sortValue: (l) => l.code, cell: (l) => <span className="font-mono text-xs font-medium">{l.code}</span> },
          { header: t("name"), sortValue: (l) => l.name, cell: (l) => <span className="font-medium">{l.name}</span> },
          { header: t("kind"), hideBelow: "sm", cell: (l) => <Badge>{t(`kinds.${l.kind}`)}</Badge> },
          { header: t("branch"), hideBelow: "md", cell: (l) => branchName(l.branch_id) },
          { header: t("status"), hideBelow: "md", cell: (l) => <StatusBadge status={l.is_active ? "active" : "inactive"} /> },
        ]}
      />
      <NewLocation open={creating} onClose={() => setCreating(false)} />
    </>
  );
}

function NewLocation({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation("inventory");
  const qc = useQueryClient();
  const f = useFormState({ company_id: "", branch_id: "", code: "", name: "", kind: "store" });
  const { companyId, companies, branches } = useFormCompany(f.values.company_id);
  const needsBranch = f.values.kind === "store" || f.values.kind === "warehouse";

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/inventory/locations", { body: {
      company_id: companyId, branch_id: needsBranch ? (f.values.branch_id || branches[0]?.id || null) : null,
      code: f.values.code.trim(), name: f.values.name.trim(), kind: f.values.kind as Kind } })),
    onSuccess: (l) => { void qc.invalidateQueries({ queryKey: ["inv-locations"] }); toast(t("locationCreated", { name: l.name }), "ok"); f.reset(); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Drawer open={open} onClose={onClose} title={t("newLocation")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="new-location" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="new-location" onSubmit={submit} className="space-y-4">
        <CompanyField label={t("company")} value={companyId} onChange={(v) => f.set("company_id", v)} companies={companies} />
        <Field label={t("kind")} hint={t(`kindHints.${f.values.kind}`)}>
          <Select {...f.bind("kind")}>{KINDS.map((k) => <option key={k} value={k}>{t(`kinds.${k}`)}</option>)}</Select>
        </Field>
        {needsBranch && branches.length > 0 && (
          <Field label={t("branch")} error={f.error("branch_id")}>
            <Select value={f.values.branch_id || branches[0]?.id} onChange={(e) => f.set("branch_id", e.target.value)}>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select>
          </Field>
        )}
        <Field label={t("code")} required error={f.error("code")} hint={t("codeHint")}><Input {...f.bind("code")} required maxLength={20} autoFocus /></Field>
        <Field label={t("name")} required error={f.error("name")}><Input {...f.bind("name")} required maxLength={200} /></Field>
      </form>
    </Drawer>
  );
}
