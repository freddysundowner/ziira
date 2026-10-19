import { Plus } from "lucide-react";
import { useState } from "react";

import { api, Badge, Button, Card, Input, Select, unwrap, useTranslation } from "@/sdk";

import { useBays, useCatalogAction } from "../hooks";

/** The places in the workshop a job is worked on (a bay, a lift, the paint booth), per branch. */
export function BaysCard({ companyId, branches }: { companyId: string; branches: readonly { id: string; name: string }[] }) {
  const { t } = useTranslation("jobs");
  const bays = useBays(companyId, undefined, true);
  const [name, setName] = useState("");
  const [branch, setBranch] = useState("");
  const branchId = branch || branches[0]?.id || "";
  const add = useCatalogAction(() => unwrap(api.POST("/api/v1/jobs/bays", { body: { company_id: companyId, branch_id: branchId, name: name.trim(), position: 0 } })), { done: t("garage.catalog.saved"), onDone: () => setName("") });
  const toggle = useCatalogAction((v: { id: string; active: boolean }) => unwrap(api.PATCH("/api/v1/jobs/bays/{bay_id}", { params: { path: { bay_id: v.id } }, body: { is_active: v.active } })));
  const named = new Map(branches.map((b) => [b.id, b.name]));
  return (
    <Card title={t("garage.bays.settingsTitle")} description={t("garage.bays.settingsHint")}>
      <ul className="mb-3 divide-y divide-line text-sm">
        {(bays.data ?? []).map((b) => (
          <li key={b.id} className="flex items-center justify-between gap-3 py-2">
            <span className={b.is_active ? "font-medium" : "text-muted line-through"}>{b.name}{branches.length > 1 && <Badge tone="neutral" className="ml-2">{named.get(b.branch_id)}</Badge>}</span>
            <Button size="sm" variant="ghost" onClick={() => toggle.mutate({ id: b.id, active: !b.is_active })}>{b.is_active ? t("garage.bays.retire") : t("garage.bays.restore")}</Button>
          </li>
        ))}
        {(bays.data ?? []).length === 0 && <li className="py-2 text-muted">{t("garage.bays.noBays")}</li>}
      </ul>
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim() && branchId) add.mutate(undefined); }}>
        {branches.length > 1 && <Select aria-label={t("filters.branch")} className="w-auto" value={branchId} onChange={(e) => setBranch(e.target.value)}>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select>}
        <Input className="min-w-40 flex-1" aria-label={t("garage.bays.newBay")} placeholder={t("garage.bays.newBay")} maxLength={60} value={name} onChange={(e) => setName(e.target.value)} />
        <Button type="submit" variant="secondary" loading={add.isPending} disabled={!name.trim()}><Plus className="h-4 w-4" />{t("common.add")}</Button>
      </form>
    </Card>
  );
}
