import { Search } from "lucide-react";

import { Checkbox, Input, Select, useTranslation } from "@/sdk";

import { usePeople } from "../hooks";

export interface Filters {
  branchId: string;
  assigneeId: string;
  search: string;
  late: boolean;
  showClosed: boolean;
  waitingOn: string;
}

export const NO_FILTERS: Filters = { branchId: "", assigneeId: "", search: "", late: false, showClosed: false, waitingOn: "" };

/** The filters above the board and the list. A branch picker shows only for people with more than one branch. */
export function JobFilters({ value, onChange, branches }: { value: Filters; onChange: (f: Filters) => void; branches: readonly { id: string; name: string }[] }) {
  const { t } = useTranslation("jobs");
  const people = usePeople();
  const set = <K extends keyof Filters>(key: K, v: Filters[K]) => onChange({ ...value, [key]: v });
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <div className="relative min-w-[200px] max-w-sm flex-1">
        <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted" />
        <Input aria-label={t("filters.search")} placeholder={t("filters.search")} className="pl-8" value={value.search} onChange={(e) => set("search", e.target.value)} />
      </div>
      {branches.length > 1 && (
        <Select aria-label={t("filters.branch")} className="w-auto" value={value.branchId} onChange={(e) => set("branchId", e.target.value)}>
          <option value="">{t("filters.allBranches")}</option>
          {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </Select>
      )}
      <Select aria-label={t("filters.assignee")} className="w-auto" value={value.assigneeId} onChange={(e) => set("assigneeId", e.target.value)}>
        <option value="">{t("filters.everyone")}</option>
        {(people.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </Select>
      <Select aria-label={t("garage.filters.waitingOn")} className="w-auto" value={value.waitingOn} onChange={(e) => set("waitingOn", e.target.value)}>
        <option value="">{t("garage.filters.anything")}</option>
        {(["parts", "approval", "insurer"] as const).map((w) => <option key={w} value={w}>{t(`garage.waiting.${w}`)}</option>)}
      </Select>
      <Checkbox label={t("filters.late")} checked={value.late} onChange={(e) => set("late", e.target.checked)} />
      <Checkbox label={t("filters.closed")} checked={value.showClosed} onChange={(e) => set("showClosed", e.target.checked)} />
    </div>
  );
}
