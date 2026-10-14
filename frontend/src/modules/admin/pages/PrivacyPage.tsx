import { Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  api, Badge, Button, DataTable, formatDate, Pager, PageHeader, Select, StatusBadge, Tabs, today, unwrap, useCan, usePagedList, useTranslation,
} from "@/sdk";

import { useSelectedCompany } from "../components/useSelectedCompany";
import NewRequestModal from "./privacy/NewRequestModal";
import { dueState, REQUEST_STATUSES } from "./privacy/model";
import RetentionTab from "./privacy/RetentionTab";
import { useUserNames } from "./privacy/useUserNames";

type Tab = "requests" | "retention";

/** Data subject requests (a person asks to see, correct or erase what is held about them) and the retention view. */
export default function PrivacyPage() {
  const { t } = useTranslation("kernel");
  const [tab, setTab] = useState<Tab>("requests");
  const [status, setStatus] = useState("");
  const [creating, setCreating] = useState(false);
  const canManage = useCan("privacy.manage");
  const { companyId, picker } = useSelectedCompany(t("company"));
  const list = usePagedList(["privacy-requests", status, companyId], (limit, offset) =>
    unwrap(api.GET("/api/v1/privacy/requests", { params: { query: { status: (status || undefined) as never, company_id: companyId, limit, offset } } })), 25, tab === "requests");
  const day = today();
  const userName = useUserNames();

  return (
    <>
      <PageHeader title={t("privacy")} description={t("dsr.hint")}
        actions={canManage && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("dsr.newRequest")}</Button>} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "requests", label: t("dsr.tabRequests") }, { id: "retention", label: t("dsr.tabRetention") }]} />
      {picker}
      {tab === "retention" ? <RetentionTab companyId={companyId} /> : (
        <DataTable
          rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(r) => r.id}
          rowHref={(r) => `/admin/privacy/${r.id}`}
          toolbar={
            <Select aria-label={t("status")} className="w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>
              {REQUEST_STATUSES.map((s) => <option key={s} value={s}>{t(`dsr.statusName.${s}`)}</option>)}
            </Select>
          }
          footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
          empty={{ title: status ? t("dsr.noneWithStatus") : t("dsr.none"), hint: status ? undefined : t("dsr.noneHint"), action: canManage && !status ? <Button onClick={() => setCreating(true)}>{t("dsr.newRequest")}</Button> : undefined }}
          columns={[
            { header: t("dsr.number"), cell: (r) => <Link className="font-medium hover:underline" to={`/admin/privacy/${r.id}`}>{r.number}</Link> },
            { header: t("dsr.type"), cell: (r) => t(`dsr.typeName.${r.request_type}`, { defaultValue: r.request_type }) },
            { header: t("dsr.subject"), hideBelow: "sm", cell: (r) => r.subject_masked },
            { header: t("dsr.due"), cell: (r) => <DueCell due={r.due_date} state={dueState(r, day)} /> },
            { header: t("dsr.handler"), hideBelow: "lg", cell: (r) => userName(r.handled_by) },
            { header: t("status"), cell: (r) => <StatusBadge status={r.status} /> },
          ]}
        />
      )}
      <NewRequestModal open={creating} onClose={() => setCreating(false)} />
    </>
  );
}

function DueCell({ due, state }: { due: string; state: "done" | "overdue" | "soon" | "later" }) {
  const { t } = useTranslation("kernel");
  return (
    <span className={state === "overdue" ? "font-medium text-bad" : undefined}>
      {formatDate(due)}
      {state === "overdue" && <Badge tone="bad" className="ml-2">{t("dsr.overdue")}</Badge>}
      {state === "soon" && <Badge tone="warn" className="ml-2">{t("dsr.dueSoon")}</Badge>}
    </span>
  );
}
