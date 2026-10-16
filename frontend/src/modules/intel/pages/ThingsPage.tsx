import { LayoutGrid, List } from "lucide-react";
import { useState } from "react";

import {
  Button, Checkbox, EmptyState, ErrorState, Input, PageHeader, Select, SkeletonRows, Slot, Tabs, useCan, useCompany, useDebounced, useSession, useTranslation,
} from "@/sdk";

import { useAreaLabel } from "../components/Badges";
import FindingsTable from "../components/FindingsTable";
import ThingCard from "../components/ThingCard";
import { AREAS } from "../logic";
import { FINDINGS_BANNER } from "../public";
import { type GroupedFilters, useGrouped, type View } from "../useGrouped";

const STEP = 20;

/** Everything Ziira noticed: waiting for you, someone is on it, or finished. Similar things are one card; a table is one click away. */
export default function ThingsPage() {
  const { t } = useTranslation("intel");
  const areaLabel = useAreaLabel();
  const canManage = useCan("findings.manage");
  const canRespond = useCan("findings.respond");
  const { companies, company } = useCompany();
  const { enabledUnits } = useSession();
  const showSource = enabledUnits.has("connect");
  const [view, setView] = useState<View>("open");
  const [mode, setMode] = useState<"cards" | "table">("cards");
  const [shown, setShown] = useState(STEP);
  const [band, setBand] = useState("");
  const [area, setArea] = useState("");
  const [companyId, setCompanyId] = useState("");
  const [branchId, setBranchId] = useState("");
  const [source, setSource] = useState("");
  const [mine, setMine] = useState(!canManage && canRespond);
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim());
  const filters: GroupedFilters = { band, area, companyId, branchId, search: q, mine };
  const filtered = !!(band || area || companyId || branchId || q || mine || source);
  const list = useGrouped(view, shown, filters);
  const branches = companies.find((c) => c.id === (companyId || (companies.length === 1 ? companies[0].id : "")))?.branches ?? [];
  const data = list.data;

  return (
    <>
      <PageHeader title={t("things.title")} description={t("things.hint")}
        actions={
          <div className="inline-flex rounded-lg border border-line p-0.5" role="group" aria-label={t("things.display")}>
            <Button size="sm" variant={mode === "cards" ? "primary" : "ghost"} aria-pressed={mode === "cards"} onClick={() => setMode("cards")}><LayoutGrid className="h-4 w-4" aria-hidden />{t("things.cards")}</Button>
            <Button size="sm" variant={mode === "table" ? "primary" : "ghost"} aria-pressed={mode === "table"} onClick={() => setMode("table")}><List className="h-4 w-4" aria-hidden />{t("things.table")}</Button>
          </div>
        } />
      <Slot name={FINDINGS_BANNER} props={{ companyId: companyId || company?.id || "" }} />
      <Tabs value={view} onChange={(v) => { setView(v); setShown(STEP); }}
        tabs={[{ id: "open", label: t("things.tab.open") }, { id: "waiting", label: t("things.tab.waiting") }, { id: "done", label: t("things.tab.done") }]} />
      <p className="mb-3 text-sm text-muted">{t(`things.tabHint.${view}`)}</p>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input className="min-w-40 max-w-xs flex-1" aria-label={t("search")} placeholder={t("search")} value={search} onChange={(e) => setSearch(e.target.value)} />
        <Select aria-label={t("severityFilter")} className="w-auto" value={band} onChange={(e) => setBand(e.target.value)}>
          <option value="">{t("allSeverities")}</option>
          {(["urgent", "soon", "look"] as const).map((b) => <option key={b} value={b}>{t(`band.${b}`)}</option>)}
        </Select>
        <Select aria-label={t("areaFilter")} className="w-auto" value={area} onChange={(e) => setArea(e.target.value)}>
          <option value="">{t("allAreas")}</option>
          {AREAS.map((x) => <option key={x} value={x}>{areaLabel(x)}</option>)}
        </Select>
        {showSource && (
          <Select aria-label={t("source.filter")} className="w-auto" value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">{t("source.all")}</option>
            <option value="connected">{t("source.connected")}</option>
            <option value="ziira">{t("source.ziira")}</option>
          </Select>
        )}
        {companies.length > 1 && (
          <Select aria-label={t("company")} className="w-auto" value={companyId} onChange={(e) => { setCompanyId(e.target.value); setBranchId(""); }}>
            <option value="">{t("allCompanies")}</option>
            {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
        )}
        {branches.length > 1 && (
          <Select aria-label={t("branch")} className="w-auto" value={branchId} onChange={(e) => setBranchId(e.target.value)}>
            <option value="">{t("allBranches")}</option>
            {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </Select>
        )}
        {(canRespond || canManage) && <Checkbox label={t("assignedToMe")} checked={mine} onChange={(e) => setMine(e.target.checked)} />}
      </div>
      {mode === "table" ? <FindingsTable view={view} filters={filters} source={source} filtered={filtered} /> : list.error ? <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />
        : !data ? <SkeletonRows rows={5} cols={2} />
          : data.groups.length === 0 ? <EmptyState title={filtered ? t("noMatch") : t(`things.empty.${view}`)} hint={filtered ? t("noMatchHint") : t(`things.emptyHint.${view}`)} />
            : (
              <div className="space-y-3">
                <p className="text-sm text-muted">{t("things.count", { things: data.total_findings, cards: data.total_groups })}</p>
                <ul className="space-y-3">{data.groups.map((g) => <li key={g.key}><ThingCard group={g} actions={view !== "done"} /></li>)}</ul>
                {data.total_groups > shown && <div className="flex justify-center"><Button variant="secondary" onClick={() => setShown(shown + STEP)}>{t("things.more")}</Button></div>}
              </div>
            )}
    </>
  );
}
