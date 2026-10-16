import { useQuery } from "@tanstack/react-query";
import { Download, MoreHorizontal, Plus } from "lucide-react";
import { useState } from "react";

import { Alert, Badge, type BadgeTone, Button, type Column, DataTable, formatDate, Menu, PageHeader, type Schemas, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap, saveText } from "../../client";
import { ReasonDialog } from "../../components/ReasonDialog";
import { useOperatorCan } from "../../me";
import { useStepUp } from "../../stepUp";
import { InvoiceFormDialog, useRefreshOperator } from "../billing/invoiceDialogs";
import { IssueLicenceDialog } from "./IssueLicenceDialog";

type Licence = Schemas["LicenceOut"];
const TONES: Record<string, BadgeTone> = { active: "ok", revoked: "bad", expired: "neutral" };

export default function LicencesPage() {
  const { t } = useTranslation("operator");
  const canIssue = useOperatorCan("platform.licences");
  const canBill = useOperatorCan("platform.billing");
  const refresh = useRefreshOperator();
  const stepUp = useStepUp();
  const [dialog, setDialog] = useState<{ kind: "issue" } | { kind: "revoke" | "invoice"; licence: Licence } | null>(null);
  const licences = useQuery({ queryKey: ["operator", "licences"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/licences")) });

  const download = async (call: () => Promise<{ filename: string; content: string }>) => {
    try {
      const file = await stepUp(call);
      saveText(file.content, file.filename);
    } catch (error) {
      if (error instanceof Error && error.message) toast(error.message, "bad");
    }
  };
  const fileOf = (l: Licence) => download(() => opUnwrap(opApi.GET("/api/v1/operator/licences/{licence_id}/file", { params: { path: { licence_id: l.id } } })));
  const revocations = () => download(() => opUnwrap(opApi.GET("/api/v1/operator/licence-revocations")));

  const columns: Column<Licence>[] = [
    { header: t("licences.number"), cell: (l) => <span className="font-mono text-sm font-medium">{l.licence_no}</span> },
    { header: t("licences.customer"), cell: (l) => <div className="min-w-0"><p className="truncate text-sm font-medium">{l.customer}</p>{l.contact_email && <p className="truncate text-xs text-muted">{l.contact_email}</p>}</div> },
    { header: t("licences.plan"), hideBelow: "md", cell: (l) => <span className="text-sm">{l.plan_code ?? "-"}</span> },
    {
      header: t("licences.includes"), hideBelow: "lg",
      cell: (l) => {
        const e = l.entitlements as { edition?: string | null; units?: string[]; max_users?: number | null; max_branches?: number | null; max_companies?: number | null };
        return (
          <div className="text-xs text-muted">
            <p title={(e.units ?? []).join(", ")}>{t("licences.unitsCount", { count: e.units?.length ?? 0 })}{e.edition ? ` · ${e.edition}` : ""}</p>
            <p>{t("plans.limitsLine", { users: e.max_users ?? t("plans.unlimited"), branches: e.max_branches ?? t("plans.unlimited"), companies: e.max_companies ?? t("plans.unlimited") })}</p>
          </div>
        );
      },
    },
    {
      header: t("licences.validUntil"),
      cell: (l) => (
        <div className="text-sm">
          <p>{l.valid_until ? formatDate(l.valid_until) : t("licences.perpetual")}</p>
          {l.update_until && <p className="text-xs text-muted">{t("licences.updatesUntil", { date: formatDate(l.update_until) })}</p>}
        </div>
      ),
    },
    { header: t("licences.instance"), hideBelow: "lg", cell: (l) => l.instance_id ? <span className="font-mono text-xs" title={l.instance_id}>{l.instance_id.slice(0, 10)}</span> : <span className="text-xs text-muted">{t("licences.anyInstance")}</span> },
    {
      header: t("licences.status"),
      cell: (l) => (
        <div><Badge tone={TONES[l.status] ?? "neutral"}>{t(`licences.statuses.${l.status}`, l.status)}</Badge>{l.revoked_reason && <p className="mt-0.5 max-w-[14rem] truncate text-xs text-muted" title={l.revoked_reason}>{l.revoked_reason}</p>}</div>
      ),
    },
    {
      header: "", align: "right",
      cell: (l) => canIssue || canBill ? (
        <Menu label={t("licences.actionsFor", { number: l.licence_no })} trigger={<MoreHorizontal className="h-5 w-5 text-muted" />} items={[
          ...(canIssue ? [{ label: t("licences.download"), onSelect: () => void fileOf(l), icon: <Download className="h-4 w-4" /> }] : []),
          ...(canBill ? [{ label: t("licences.createInvoice"), onSelect: () => setDialog({ kind: "invoice", licence: l }) }] : []),
          ...(canIssue && l.status === "active" ? [{ label: t("licences.revoke"), danger: true, onSelect: () => setDialog({ kind: "revoke", licence: l }) }] : []),
        ]} />
      ) : null,
    },
  ];

  return (
    <>
      <PageHeader title={t("licences.title")} description={t("licences.description")}
        actions={canIssue ? (
          <>
            <Button variant="secondary" onClick={() => void revocations()}><Download className="h-4 w-4" /> {t("licences.revocationList")}</Button>
            <Button onClick={() => setDialog({ kind: "issue" })}><Plus className="h-4 w-4" /> {t("licences.issue")}</Button>
          </>
        ) : undefined} />
      <Alert tone="info" className="mb-4">{t("licences.help")}</Alert>
      <DataTable rows={licences.data} columns={columns} rowKey={(l) => l.id} loading={licences.isPending} error={licences.isError ? licences.error.message : null} onRetry={() => void licences.refetch()}
        searchText={(l) => `${l.licence_no} ${l.customer} ${l.contact_email ?? ""}`} searchPlaceholder={t("licences.search")} pageSize={25}
        empty={{ title: t("licences.empty"), hint: canIssue ? t("licences.emptyHint") : undefined }} />

      {dialog?.kind === "issue" && <IssueLicenceDialog onClose={() => setDialog(null)} />}
      {dialog?.kind === "invoice" && <InvoiceFormDialog licenceId={dialog.licence.id} onClose={() => setDialog(null)} />}
      {dialog?.kind === "revoke" && (
        <ReasonDialog title={t("licences.revokeTitle", { number: dialog.licence.licence_no })} intro={t("licences.revokeMessage")} confirmLabel={t("licences.revoke")} danger
          run={(reason) => opUnwrap(opApi.POST("/api/v1/operator/licences/{licence_id}/revoke", { params: { path: { licence_id: dialog.licence.id } }, body: { reason } }))}
          onDone={() => { toast(t("licences.revoked"), "ok"); refresh(); }} onClose={() => setDialog(null)} />
      )}
    </>
  );
}
