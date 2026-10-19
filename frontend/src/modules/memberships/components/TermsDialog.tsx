import { useEffect, useState } from "react";

import { api, Alert, Button, Checkbox, Field, Input, Modal, Skeleton, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

/** Show the business's current terms and record that a person accepted them by typing their name. */
export function TermsDialog({ open, onClose, customerId, companyId, method = "desk", personName, onDone }: {
  open: boolean; onClose: () => void; customerId: string; companyId: string; method?: "desk" | "kiosk"; personName?: string | null; onDone?: () => void;
}) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const [typed, setTyped] = useState("");
  const [agreed, setAgreed] = useState(false);
  useEffect(() => { if (open) { setTyped(personName ?? ""); setAgreed(false); } }, [open, personName]);
  const versions = useQuery({
    enabled: open && !!companyId, queryKey: ["memberships", "waiver-versions", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/waiver/versions", { params: { query: { company_id: companyId } } })),
  });
  const newest = versions.data?.reduce<(typeof versions.data)[number] | undefined>((a, b) => (!a || b.version > a.version ? b : a), undefined);
  const accept = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/customers/{customer_id}/waiver", {
      params: { path: { customer_id: customerId } }, body: { accepted_name: typed.trim(), method, version: newest?.version ?? null } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["memberships"] });
      toast(t("waiver.accepted"), "ok");
      onDone?.();
      onClose();
    },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <Modal open={open} onClose={onClose} title={t("waiver.dialogTitle")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button loading={accept.isPending} disabled={!typed.trim() || !agreed || !newest} onClick={() => accept.mutate()}>{t("waiver.record")}</Button></>}>
      <div className="space-y-4">
        {versions.isLoading && <Skeleton className="h-32 w-full" />}
        {versions.error && <Alert tone="bad">{versions.error.message} <button type="button" className="underline" onClick={() => void versions.refetch()}>{t("retry")}</button></Alert>}
        {versions.data && !newest && <Alert tone="warn">{t("waiver.noneYet")}</Alert>}
        {newest && (
          <>
            <div>
              <p className="font-semibold">{newest.title}</p>
              <p className="text-xs text-muted">{t("waiver.version", { version: newest.version })}</p>
              <div className="mt-2 max-h-56 overflow-y-auto whitespace-pre-wrap rounded-lg bg-sunken p-3 text-sm">{newest.body}</div>
            </div>
            <Checkbox checked={agreed} onChange={(e) => setAgreed(e.target.checked)} label={t("waiver.agree")} />
            <Field label={t("waiver.typeName")} hint={t("waiver.typeNameHint")} required><Input value={typed} maxLength={200} onChange={(e) => setTyped(e.target.value)} /></Field>
          </>
        )}
      </div>
    </Modal>
  );
}
