import { BadgeCheck, Eye, GitBranchPlus, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, Card, ConfirmDialog, DataTable, DetailList, EmptyState, ErrorState, formatDate, Menu, Modal, SkeletonRows, StatusBadge, toast, today, unwrap, useCan, useMutation,
  useQueryClient, useSession, useTranslation, Alert, Field, Input,
} from "@/sdk";

import { inForce, ruleToForm } from "../lib/rules";
import { useRules } from "../lib/lookups";
import type { Rule } from "../lib/types";
import { RuleEditor } from "./RuleEditor";
import { RuleSummary } from "./RuleSummary";

/** The business's statutory rules, grouped by code with their versions. New rules start unverified; another person verifies them. */
export function RulesPanel({ companyId, currency }: { companyId: string; currency?: string }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const me = useSession().me?.user_id;
  const canEdit = useCan("payroll.rates");
  const rules = useRules(companyId);
  const [editor, setEditor] = useState<{ initial?: Rule } | null>(null);
  const [viewing, setViewing] = useState<Rule | null>(null);
  const [verifying, setVerifying] = useState<Rule | null>(null);
  const [deleting, setDeleting] = useState<Rule | null>(null);
  const [note, setNote] = useState("");
  const refresh = () => void qc.invalidateQueries({ queryKey: ["people", "rules"] });

  const verify = useMutation({
    mutationFn: (r: Rule) => unwrap(api.POST("/api/v1/people/rules/{rule_id}/verify", { params: { path: { rule_id: r.id } }, body: { note: note.trim() || null } })),
    onSuccess: () => { refresh(); toast(t("rules.verified"), "ok"); setVerifying(null); setNote(""); },
  });
  const remove = useMutation({
    mutationFn: (r: Rule) => unwrap(api.DELETE("/api/v1/people/rules/{rule_id}", { params: { path: { rule_id: r.id } } })),
    onSuccess: () => { refresh(); toast(t("rules.deleted"), "ok"); setDeleting(null); },
  });

  const all = rules.data ?? [];
  const current = inForce(all, today());
  const groups = [...new Map(all.map((r) => [r.code, r.code])).keys()].map((code) => ({ code, versions: all.filter((r) => r.code === code) }));
  const nameOf = (r: Rule) => String((r.definition as { name?: string }).name ?? r.code);
  const unverified = all.filter((r) => !r.is_verified).length;
  const add = canEdit ? <Button onClick={() => setEditor({})}><Plus className="h-4 w-4" />{t("rules.new")}</Button> : undefined;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted">{t("rules.intro")}</p>
        {add}
      </div>
      {unverified > 0 && <Alert tone="warn">{t("rules.unverifiedWarning", { count: unverified })}</Alert>}
      {rules.error ? <Card><ErrorState message={rules.error.message} onRetry={() => void rules.refetch()} /></Card>
        : !rules.data ? <Card><SkeletonRows /></Card>
        : groups.length === 0 ? <Card><EmptyState title={t("rules.empty")} hint={t("rules.emptyHint")} action={add} /></Card>
        : groups.map((g) => (
          <Card key={g.code} flush title={<span>{nameOf(g.versions[0]!)} <span className="ml-1 font-mono text-xs font-normal text-muted">{g.code}</span></span>}
            description={t(`rules.kinds.${(g.versions[0]!.definition as { kind?: string }).kind ?? "other"}`)}>
            <DataTable rows={g.versions} rowKey={(r) => r.id} empty={{ title: "" }}
              columns={[
                { header: t("rules.effectiveFrom"), cell: (r) => <span className="font-medium">{formatDate(r.effective_from)}</span> },
                { header: t("rules.effectiveTo"), hideBelow: "sm", cell: (r) => (r.effective_to ? formatDate(r.effective_to) : "—") },
                { header: t("status"), cell: (r) => (
                  <span className="flex flex-wrap gap-1.5">
                    {current.has(r.id) && <Badge tone="brand">{t("rules.inForce")}</Badge>}
                    {r.effective_from > today() && <Badge tone="info">{t("rules.upcoming")}</Badge>}
                    <StatusBadge status={r.is_verified ? "verified" : "pending"} />
                  </span>
                ) },
                { header: t("rules.source"), hideBelow: "lg", cell: (r) => <span className="line-clamp-2 max-w-xs text-xs text-muted">{r.source_reference}</span> },
                { header: "", align: "right", cell: (r) => (
                  <Menu label={t("actions")} trigger={<span className="rounded-lg px-2 py-1 text-muted hover:bg-sunken">•••</span>} items={[
                    { label: t("rules.view"), icon: <Eye className="h-4 w-4" />, onSelect: () => setViewing(r) },
                    ...(canEdit ? [
                      { label: t("rules.newVersion"), icon: <GitBranchPlus className="h-4 w-4" />, onSelect: () => setEditor({ initial: r }) },
                      ...(!r.is_verified ? [{ label: t("rules.verify"), icon: <BadgeCheck className="h-4 w-4" />, disabled: r.created_by === me, onSelect: () => setVerifying(r) }] : []),
                      "separator" as const,
                      { label: t("delete"), icon: <Trash2 className="h-4 w-4" />, danger: true, onSelect: () => setDeleting(r) },
                    ] : []),
                  ]} />
                ) },
              ]} />
          </Card>
        ))}

      <RuleEditor open={!!editor} onClose={() => setEditor(null)} companyId={companyId} currency={currency} initial={editor?.initial ? ruleToForm(editor.initial) : undefined} />
      <Modal open={!!viewing} onClose={() => setViewing(null)} size="lg" title={viewing ? nameOf(viewing) : ""} footer={<Button variant="secondary" onClick={() => setViewing(null)}>{t("close")}</Button>}>
        {viewing && (
          <div className="space-y-4">
            <DetailList items={[
              { label: t("rules.code"), value: <span className="font-mono">{viewing.code}</span> },
              { label: t("rules.effectiveFrom"), value: formatDate(viewing.effective_from) },
              { label: t("rules.effectiveTo"), value: viewing.effective_to ? formatDate(viewing.effective_to) : "—" },
              { label: t("rules.source"), value: viewing.source_reference },
              { label: t("status"), value: viewing.is_verified ? t("rules.verifiedBy", { who: viewing.verified_by ?? "—", date: formatDate(viewing.verified_at) }) : t("rules.notVerified") },
            ]} />
            <Card title={t("rules.howItWorks")}><RuleSummary form={ruleToForm(viewing)} currency={currency} /></Card>
          </div>
        )}
      </Modal>
      <Modal open={!!verifying} onClose={() => setVerifying(null)} size="md" title={t("rules.verify")}
        footer={<><Button variant="secondary" onClick={() => setVerifying(null)}>{t("cancel")}</Button><Button loading={verify.isPending} onClick={() => verifying && verify.mutate(verifying)}>{t("rules.verify")}</Button></>}>
        {verifying && (
          <div className="space-y-4">
            <p className="text-sm text-muted">{t("rules.verifyAsk", { source: verifying.source_reference })}</p>
            <Card title={t("rules.howItWorks")}><RuleSummary form={ruleToForm(verifying)} currency={currency} /></Card>
            <Field label={t("rules.verifyNote")}><Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} /></Field>
          </div>
        )}
      </Modal>
      <ConfirmDialog open={!!deleting} onClose={() => setDeleting(null)} busy={remove.isPending} danger title={t("delete")} confirmLabel={t("delete")}
        message={t("rules.deleteAsk", { name: deleting ? nameOf(deleting) : "", date: deleting ? formatDate(deleting.effective_from) : "" })} onConfirm={() => deleting && remove.mutate(deleting)} />
    </div>
  );
}
