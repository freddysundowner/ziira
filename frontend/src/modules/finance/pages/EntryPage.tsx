import { Undo2 } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  api, Alert, Badge, Button, Card, DetailList, ErrorState, Field, formatDate, humanise, Input, Modal, PageHeader, Skeleton, Textarea, today, toast, unwrap, useCan,
  useFormState, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { accountNames, useAccounts } from "../api";
import { EntryLines } from "../components/EntryLines";
import { useScope } from "../scope";

/** One posted entry with its lines. A manual entry can be reversed (once); one made by a sale or stock movement is corrected in its own document. */
export default function EntryPage() {
  const { t } = useTranslation("finance");
  const { entryId = "" } = useParams();
  const scope = useScope();
  const canReverse = useCan("journal.approve");
  const [reversing, setReversing] = useState(false);
  const entry = useQuery({ queryKey: ["finance", "entry", entryId], queryFn: () => unwrap(api.GET("/api/v1/finance/journal-entries/{entry_id}", { params: { path: { entry_id: entryId } } })) });
  const e = entry.data;
  const accounts = useAccounts(e?.company_id ?? "", true);
  const company = scope.companies.find((c) => c.id === e?.company_id);

  if (entry.error) return <ErrorState title={t("entry.notFound")} message={entry.error.message} onRetry={() => void entry.refetch()} />;
  if (!e) return <Skeleton className="h-48 w-full" />;
  const reversible = e.is_manual && !e.reversed_by && !e.reversal_of_id;
  return (
    <>
      <PageHeader back={{ to: "/finance/journal", label: t("journal.title") }} title={e.number}
        description={<span className="flex flex-wrap items-center gap-2">{formatDate(e.entry_date)}{e.reversed_by && <Badge tone="bad">{t("entry.reversed")}</Badge>}{e.reversal_of_id && <Badge tone="warn">{t("journal.reversal")}</Badge>}</span>}
        actions={<>
          <Button variant="secondary" className="no-print" onClick={() => window.print()}>{t("print")}</Button>
          {reversible && canReverse && <Button variant="danger" onClick={() => setReversing(true)}><Undo2 className="h-4 w-4" />{t("entry.reverse")}</Button>}
        </>} />
      <div className="space-y-4">
        <Card>
          <DetailList items={[
            { label: t("description"), value: e.description ?? "—" },
            { label: t("source"), value: e.is_manual ? t("journal.byHand") : humanise(e.source_type) },
            { label: t("entry.postedAt"), value: formatDate(e.posted_at, true) },
            { label: t("entry.reversalOf"), value: e.reversal_of_id ? <Link className="underline" to={`/finance/journal/${e.reversal_of_id}`}>{t("entry.open")}</Link> : "—" },
            { label: t("entry.reversedBy"), value: e.reversed_by ? <Link className="underline" to={`/finance/journal/${e.reversed_by}`}>{t("entry.open")}</Link> : "—" },
          ]} />
        </Card>
        {!e.is_manual && !e.reversal_of_id && <Alert>{t("entry.correctInSource")}</Alert>}
        <Card title={t("entry.lines")} flush>
          <EntryLines lines={e.lines} names={accountNames(accounts.data)} scope={scope} currency={company?.currency} />
        </Card>
      </div>
      <ReverseModal open={reversing} onClose={() => setReversing(false)} entryId={e.id} number={e.number} />
    </>
  );
}

function ReverseModal({ open, onClose, entryId, number }: { open: boolean; onClose: () => void; entryId: string; number: string }) {
  const { t } = useTranslation("finance");
  const qc = useQueryClient();
  const f = useFormState({ reason: "", entry_date: today() });
  const reverse = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/finance/journal-entries/{entry_id}/reverse", { params: { path: { entry_id: entryId } }, body: { reason: f.values.reason.trim(), entry_date: f.values.entry_date || null } })),
    onSuccess: (r) => { void qc.invalidateQueries({ queryKey: ["finance"] }); toast(t("entry.reversedDone", { number: r.number }), "ok"); onClose(); },
    onError: (err) => { f.fail(err); toast((err as Error).message, "bad"); },
  });
  return (
    <Modal open={open} onClose={onClose} title={t("entry.reverseTitle", { number })}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button variant="danger" loading={reverse.isPending} disabled={!f.values.reason.trim()} onClick={() => reverse.mutate()}>{t("entry.reverse")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("entry.reverseHint")}</p>
        <Field label={t("entry.reason")} required error={f.error("reason")}><Textarea {...f.bind("reason")} maxLength={500} autoFocus /></Field>
        <Field label={t("entry.reverseDate")} error={f.error("entry_date")}><Input type="date" {...f.bind("entry_date")} /></Field>
      </div>
    </Modal>
  );
}
