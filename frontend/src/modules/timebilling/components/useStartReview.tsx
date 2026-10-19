import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, Button, Field, Modal, Select, unwrap, useCompany, useMutation, useTranslation } from "@/sdk";

import { useRefresh, useRequestKey } from "../hooks";

type Target = { clientId: string; projectId?: string };

/**
 * Start an invoice review for a client (or one of their projects) and open it. One key per start, so a second tap makes
 * no second review. When the business has several branches the person says which branch issues the invoice.
 */
export function useStartReview(companyId: string) {
  const { t } = useTranslation("timebilling");
  const navigate = useNavigate();
  const refresh = useRefresh();
  const { company } = useCompany(companyId);
  const branches = company?.branches ?? [];
  const { key, renew } = useRequestKey();
  const [asking, setAsking] = useState<Target | null>(null);
  const [branch, setBranch] = useState("");
  const create = useMutation({
    mutationFn: (v: Target & { branchId: string | null }) => unwrap(api.POST("/api/v1/timebilling/invoice-reviews", {
      params: { header: { "Idempotency-Key": `${key}:${v.clientId}:${v.projectId ?? ""}:${v.branchId ?? ""}` } },
      body: { company_id: companyId, client_id: v.clientId, project_id: v.projectId ?? null, branch_id: v.branchId, include_expenses: true, include_milestones: true },
    })),
    onSuccess: (review) => { renew(); setAsking(null); void refresh(); navigate(`/time/reviews/${review.id}`); },
  });
  const start = (target: Target) => {
    if (branches.length > 1) { setBranch(branches[0]?.id ?? ""); setAsking(target); } else create.mutate({ ...target, branchId: branches[0]?.id ?? null });
  };
  const dialog = (
    <Modal open={!!asking} onClose={() => setAsking(null)} size="sm" title={t("review.branchTitle")}
      footer={<><Button variant="secondary" onClick={() => setAsking(null)}>{t("cancel")}</Button><Button loading={create.isPending} onClick={() => asking && create.mutate({ ...asking, branchId: branch })}>{t("retainer.startReview")}</Button></>}>
      <Field label={t("branch")} hint={t("review.branchHint")}>
        <Select value={branch} onChange={(e) => setBranch(e.target.value)}>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select>
      </Field>
    </Modal>
  );
  return { start, dialog, isPending: create.isPending, pending: create.variables };
}
