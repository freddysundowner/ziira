import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  api, Alert, Button, Card, ConfirmDialog, DetailList, ErrorState, formatDate, PageHeader, Skeleton, StatusBadge, toast, unwrap, useCan, useMutation, useQuery,
  useQueryClient, useTranslation,
} from "@/sdk";

import { accountNames, useAccounts } from "../api";
import { EntryLines } from "../components/EntryLines";
import { useScope } from "../scope";

/** A manual journal: draft, waiting for an approver, posted or rejected. A draft can be sent for approval (it posts at once when no rule applies). */
export default function ManualJournalPage() {
  const { t } = useTranslation("finance");
  const { manualId = "" } = useParams();
  const qc = useQueryClient();
  const scope = useScope();
  const canWrite = useCan("journal.post_manual");
  const [confirming, setConfirming] = useState(false);
  const journal = useQuery({ queryKey: ["finance", "manual", manualId], queryFn: () => unwrap(api.GET("/api/v1/finance/manual-journals/{manual_id}", { params: { path: { manual_id: manualId } } })) });
  const j = journal.data;
  const accounts = useAccounts(j?.company_id ?? "", true);
  const submit = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/finance/manual-journals/{manual_id}/submit", { params: { path: { manual_id: manualId } } })),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["finance"] });
      toast(r.status === "posted" ? t("manual.posted") : t("manual.sent"), "ok");
      setConfirming(false);
    },
    onError: () => setConfirming(false),
  });

  if (journal.error) return <ErrorState title={t("manual.notFound")} message={journal.error.message} onRetry={() => void journal.refetch()} />;
  if (!j) return <Skeleton className="h-48 w-full" />;
  const currency = scope.companies.find((c) => c.id === j.company_id)?.currency;
  return (
    <>
      <PageHeader back={{ to: "/finance/journal", label: t("journal.title") }} title={j.number}
        description={<span className="flex items-center gap-2">{formatDate(j.entry_date)}<StatusBadge status={j.status} /></span>}
        actions={j.status === "draft" && canWrite && <Button onClick={() => setConfirming(true)}>{t("manual.submit")}</Button>} />
      <div className="space-y-4">
        {j.status === "draft" && <Alert tone="warn">{t("manual.draftHint")}</Alert>}
        {j.status === "pending_approval" && <Alert tone="warn">{t("manual.pendingHint")}</Alert>}
        {j.status === "rejected" && <Alert tone="bad">{t("manual.rejectedHint")}</Alert>}
        <Card>
          <DetailList items={[
            { label: t("description"), value: j.description },
            { label: t("entry.entry"), value: j.entry_id ? <Link className="underline" to={`/finance/journal/${j.entry_id}`}>{t("entry.open")}</Link> : "—" },
          ]} />
        </Card>
        <Card title={t("entry.lines")} flush>
          <EntryLines lines={j.lines} names={accountNames(accounts.data)} scope={scope} currency={currency} />
        </Card>
      </div>
      <ConfirmDialog open={confirming} onClose={() => setConfirming(false)} busy={submit.isPending} title={t("manual.submit")} confirmLabel={t("manual.submit")}
        message={t("manual.submitAsk")} onConfirm={() => submit.mutate()} />
    </>
  );
}
