import { Plus } from "lucide-react";
import { useState } from "react";

import { Badge, Button, DataTable, PageHeader, useCan, useTranslation } from "@/sdk";

import { BranchPicker } from "../components/BranchBar";
import { ResourceForm } from "../components/ResourceForm";
import { useBranch, useResources } from "../hooks";
import type { Resource } from "../types";

const DAYS = [0, 1, 2, 3, 4, 5, 6];

export default function ResourcesPage() {
  const { t } = useTranslation("bookings");
  const canSetup = useCan("bookings.setup");
  const { branches, branchId, setBranchId } = useBranch();
  const list = useResources(branchId, false);
  const [editing, setEditing] = useState<Resource | "new" | null>(null);

  return (
    <>
      <PageHeader title={t("resources.title")} description={t("resources.hint")}
        actions={<><BranchPicker branches={branches} value={branchId} onChange={setBranchId} />{canSetup && <Button onClick={() => setEditing("new")}><Plus className="h-4 w-4" />{t("resources.new")}</Button>}</>} />
      <DataTable
        rows={list.data} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()} rowKey={(r) => r.id}
        empty={{ title: t("resources.empty"), hint: t("resources.emptyHint"), action: canSetup ? <Button onClick={() => setEditing("new")}>{t("resources.new")}</Button> : undefined }}
        columns={[
          { header: t("resources.name"), sortValue: (r) => r.name, cell: (r) => (canSetup ? <button type="button" className="text-left font-medium hover:underline" onClick={() => setEditing(r)}>{r.name}</button> : <span className="font-medium">{r.name}</span>) },
          { header: t("resources.kind"), hideBelow: "sm", cell: (r) => t(`kinds.${r.kind}`, r.kind) },
          { header: t("resources.workingDays"), hideBelow: "md", cell: (r) => DAYS.filter((d) => r.hours.some((h) => h.weekday === d)).map((d) => t(`weekdaysShort.${d}`)).join(" ") || t("resources.noHours") },
          { header: t("resources.online"), hideBelow: "lg", cell: (r) => (r.show_publicly ? t("yes") : t("no")) },
          { header: t("status.label"), cell: (r) => <Badge tone={r.is_active ? "ok" : "neutral"}>{r.is_active ? t("resources.activeBadge") : t("resources.inactiveBadge")}</Badge> },
        ]}
      />
      <ResourceForm open={editing !== null} onClose={() => setEditing(null)} resource={editing && editing !== "new" ? editing : undefined} />
    </>
  );
}
