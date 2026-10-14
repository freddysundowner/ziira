import { Plus } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, DataTable, Drawer, Field, Input, PageHeader, Pager, Select, Tabs, toast, unwrap, useCan, useDebounced, useFormState, useMutation, usePagedList,
  useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

import { FollowUps } from "../components/FollowUps";
import { LeadDetail } from "../components/LeadDetail";
import { LeadForm, useSources } from "../components/LeadForm";
import { leadTone } from "../logic";

const STATUSES = ["new", "contacted", "qualified", "converted", "lost"] as const;

/** Sales leads, the follow-ups on the signed-in person's plate, and where leads come from. */
export default function LeadsPage() {
  const { t } = useTranslation("crm");
  const [tab, setTab] = useState<"leads" | "mine" | "sources">("leads");
  return (
    <>
      <PageHeader title={t("leadsTitle")} description={t("leadsHint")} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "leads", label: t("leads") }, { id: "mine", label: t("myFollowUps") }, { id: "sources", label: t("sources") }]} />
      {tab === "leads" && <Leads />}
      {tab === "mine" && <FollowUps />}
      {tab === "sources" && <Sources />}
    </>
  );
}

function Leads() {
  const { t } = useTranslation("crm");
  const can = useCan("leads.manage");
  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<Schemas["LeadOut"] | null>(null);
  const q = useDebounced(search.trim());
  const sources = useSources();
  const list = usePagedList(["leads", q, status], (limit, offset) =>
    unwrap(api.GET("/api/v1/crm/leads", { params: { query: { search: q || undefined, status: status || undefined, limit, offset } } })));
  const filtered = !!(q || status);

  return (
    <>
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(l) => l.id}
        toolbar={
          <>
            <Input className="max-w-xs" aria-label={t("search")} placeholder={t("searchLeads")} value={search} onChange={(e) => setSearch(e.target.value)} />
            <Select className="w-40" aria-label={t("stage")} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStages")}</option>{STATUSES.map((s) => <option key={s} value={s}>{t(`leadStatuses.${s}`)}</option>)}
            </Select>
            {can && <Button className="ml-auto" onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("newLead")}</Button>}
          </>
        }
        empty={{ title: filtered ? t("noLeadMatch") : t("noLeads"), hint: filtered ? undefined : t("noLeadsHint"), action: can && !filtered ? <Button onClick={() => setCreating(true)}>{t("newLead")}</Button> : undefined }}
        columns={[
          { header: t("name"), sortValue: (l) => l.name, cell: (l) => <button className="text-left font-medium hover:underline" onClick={() => setOpen(l)}>{l.name}</button> },
          { header: t("businessName"), hideBelow: "sm", cell: (l) => l.business_name ?? "—" },
          { header: t("phone"), hideBelow: "md", cell: (l) => l.phone ?? "—" },
          { header: t("source"), hideBelow: "lg", cell: (l) => sources.data?.find((s) => s.id === l.source_id)?.name ?? "—" },
          { header: t("stage"), cell: (l) => <Badge tone={leadTone(l.status)}>{t(`leadStatuses.${l.status}`, l.status)}</Badge> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <LeadForm open={creating} onClose={() => setCreating(false)} />
      <LeadDetail lead={open} onClose={() => setOpen(null)} />
    </>
  );
}

function Sources() {
  const { t } = useTranslation("crm");
  const qc = useQueryClient();
  const can = useCan("leads.manage");
  const [open, setOpen] = useState(false);
  const q = useSources();
  const f = useFormState({ name: "" });
  const create = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/crm/lead-sources", { body: { name: f.values.name.trim() } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["lead-sources"] }); toast(t("sourceAdded"), "ok"); f.reset(); setOpen(false); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  return (
    <>
      <DataTable rows={q.data} loading={q.isLoading} error={q.error?.message} onRetry={() => void q.refetch()} rowKey={(s) => s.id}
        toolbar={can && <Button className="ml-auto" onClick={() => setOpen(true)}><Plus className="h-4 w-4" />{t("newSource")}</Button>}
        empty={{ title: t("noSources"), hint: t("sourcesHint") }}
        columns={[{ header: t("name"), cell: (s) => <span className="font-medium">{s.name}</span> }]} />
      <Drawer open={open} onClose={() => setOpen(false)} title={t("newSource")}
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>{t("cancel")}</Button><Button type="submit" form="source-form" loading={create.isPending}>{t("save")}</Button></>}>
        <form id="source-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <Field label={t("name")} required hint={t("sourceExample")} error={f.error("name")}><Input {...f.bind("name")} required autoFocus maxLength={100} /></Field>
        </form>
      </Drawer>
    </>
  );
}
