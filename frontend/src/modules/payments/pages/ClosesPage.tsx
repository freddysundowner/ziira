import { Lock } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, DataTable, Drawer, Field, formatDate, PageHeader, Pager, Select, Textarea, toast, unwrap, useCan, useCompany, useMutation, usePagedList,
  useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

import { Amount } from "../components/Amount";
import { CloseDay } from "../components/CloseDay";
import { closeTone } from "../logic";

const STATUSES = ["open", "submitted", "locked", "reopened"] as const;

/** Each branch's daily close: takings counted, variance explained, then locked. A locked day can be reopened with a reason. */
export default function ClosesPage() {
  const { t } = useTranslation("payments");
  const qc = useQueryClient();
  const canClose = useCan("close.submit");
  const canReopen = useCan("close.reopen");
  const { company } = useCompany();
  const [status, setStatus] = useState("");
  const [branchId, setBranchId] = useState("");
  const [closing, setClosing] = useState(false);
  const [reopening, setReopening] = useState<Schemas["CloseOut"] | null>(null);
  const [reason, setReason] = useState("");
  const branches = company?.branches ?? [];
  const list = usePagedList(["closes", status, branchId], (limit, offset) =>
    unwrap(api.GET("/api/v1/payments/closes", { params: { query: { status: status || undefined, branch_id: branchId || undefined, limit, offset } } })));
  const reopen = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/payments/closes/{close_id}/reopen", { params: { path: { close_id: reopening?.id ?? "" } }, body: { reason: reason.trim() } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["closes"] }); toast(t("reopenRequested"), "ok"); setReopening(null); setReason(""); },
  });

  return (
    <>
      <PageHeader title={t("closesTitle")} description={t("closesHint")} actions={canClose && <Button onClick={() => setClosing(true)}><Lock className="h-4 w-4" />{t("closeDay")}</Button>} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(c) => c.id}
        toolbar={
          <>
            {branches.length > 1 && (
              <Select className="w-48" aria-label={t("branch")} value={branchId} onChange={(e) => setBranchId(e.target.value)}>
                <option value="">{t("allBranches")}</option>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </Select>
            )}
            <Select className="w-44" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>{STATUSES.map((s) => <option key={s} value={s}>{t(`closeStatuses.${s}`)}</option>)}
            </Select>
          </>
        }
        empty={{ title: t("noCloses"), hint: t("noClosesHint"), action: canClose ? <Button onClick={() => setClosing(true)}>{t("closeDay")}</Button> : undefined }}
        columns={[
          { header: t("day"), sortValue: (c) => c.business_date, cell: (c) => <span className="font-medium">{formatDate(c.business_date)}</span> },
          { header: t("branch"), hideBelow: "sm", cell: (c) => branches.find((b) => b.id === c.branch_id)?.name ?? "—" },
          { header: t("cashBanked"), hideBelow: "md", align: "right", cell: (c) => (c.cash_banked ? <Amount value={c.cash_banked} companyId={c.company_id} /> : "—") },
          { header: t("variance"), align: "right", cell: (c) => <span className={Number(c.variance) !== 0 ? "font-medium text-bad" : undefined}><Amount value={c.variance} companyId={c.company_id} /></span> },
          { header: t("explanation"), hideBelow: "lg", cell: (c) => c.explanation ?? "—" },
          { header: t("status"), cell: (c) => <Badge tone={closeTone(c.status)}>{t(`closeStatuses.${c.status}`, c.status)}</Badge> },
          { header: "", align: "right", cell: (c) => canReopen && (c.status === "locked" || c.status === "submitted") && <Button size="sm" variant="ghost" onClick={() => setReopening(c)}>{t("reopen")}</Button> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <CloseDay open={closing} onClose={() => setClosing(false)} />
      <Drawer open={!!reopening} onClose={() => setReopening(null)} title={t("reopen")}
        footer={<><Button variant="secondary" onClick={() => setReopening(null)}>{t("cancel")}</Button><Button loading={reopen.isPending} disabled={!reason.trim()} onClick={() => reopen.mutate()}>{t("reopen")}</Button></>}>
        <p className="mb-4 text-sm text-muted">{t("reopenHint", { date: reopening ? formatDate(reopening.business_date) : "" })}</p>
        <Field label={t("reason")} required><Textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} autoFocus /></Field>
      </Drawer>
    </>
  );
}
