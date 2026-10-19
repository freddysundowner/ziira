import { Copy } from "lucide-react";
import { useState } from "react";

import { api, Alert, Button, Checkbox, Field, Input, Modal, toast, unwrap, useTranslation } from "@/sdk";

import { useEstimateAction } from "../hooks";
import type { Estimate } from "../types";

/** Send an estimate: the customer's link is shown once, with a button to copy it; optionally a message goes to the customer too. */
export function SendEstimateDialog({ estimate, onClose }: { estimate: Estimate | null; onClose: () => void }) {
  const { t } = useTranslation("jobs");
  const [tell, setTell] = useState(false);
  const [link, setLink] = useState("");
  const send = useEstimateAction((e: Estimate) => unwrap(api.POST("/api/v1/jobs/estimates/{estimate_id}/send", { params: { path: { estimate_id: e.id } }, body: { tell_customer: tell } })),
    { onDone: (r) => setLink(`${window.location.origin}${r.link_path}`) });
  const close = () => { setLink(""); setTell(false); onClose(); };
  const copy = async () => { try { await navigator.clipboard.writeText(link); toast(t("estimates.copied"), "ok"); } catch { toast(t("estimates.copyFailed"), "bad"); } };
  return (
    <Modal open={estimate !== null} onClose={close} title={link ? t("estimates.sentTitle") : t("estimates.sendTitle", { version: estimate?.version ?? 0 })} size="sm"
      footer={link ? <Button onClick={close}>{t("common.done")}</Button> : <><Button variant="secondary" onClick={close}>{t("common.cancel")}</Button><Button loading={send.isPending} onClick={() => estimate && send.mutate(estimate)}>{t("estimates.send")}</Button></>}>
      {link ? (
        <div className="space-y-4">
          <Alert tone="warn">{t("estimates.linkOnce")}</Alert>
          <Field label={t("estimates.link")}>
            <div className="flex gap-2"><Input readOnly value={link} onFocus={(e) => e.currentTarget.select()} /><Button variant="secondary" onClick={() => void copy()}><Copy className="h-4 w-4" />{t("estimates.copy")}</Button></div>
          </Field>
          {tell && <p className="text-sm text-muted">{t("estimates.told")}</p>}
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-muted">{t("estimates.sendHint")}</p>
          <Checkbox label={t("estimates.tell")} checked={tell} onChange={(e) => setTell(e.target.checked)} />
        </div>
      )}
    </Modal>
  );
}
