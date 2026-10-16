import { useState } from "react";

import { Alert, api, Button, Field, Modal, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { refreshFindings } from "../refresh";
import PersonPicker from "./PersonPicker";

/** Give a card to someone: every thing in it goes to that person, who then sees them in their list. */
export default function AssignGroupDialog({ ids, open, onClose }: { ids: string[]; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("intel");
  const qc = useQueryClient();
  const [person, setPerson] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const save = useMutation({
    meta: { silent: true },
    mutationFn: async () => { for (const id of ids) await unwrap(api.POST("/api/v1/intel/findings/{finding_id}/assign", { params: { path: { finding_id: id } }, body: { user_id: person } })); },
    onSuccess: () => { refreshFindings(qc); toast(t("done.assign"), "ok"); close(); },
    onError: (e) => { setProblem(e.message); refreshFindings(qc); },
  });
  function close() { setPerson(""); setProblem(null); onClose(); }
  return (
    <Modal open={open} onClose={close} title={t("dialog.assign")}
      footer={<><Button variant="secondary" onClick={close}>{t("cancel")}</Button><Button loading={save.isPending} disabled={!person} onClick={() => save.mutate()}>{t("confirm.assign")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{ids.length > 1 ? t("assignMany", { count: ids.length }) : t("dialogHint.assign")}</p>
        <Field label={t("person")} hint={t("assignPersonHint")}><PersonPicker value={person} onChange={setPerson} /></Field>
        {problem && <Alert tone="bad">{problem}</Alert>}
      </div>
    </Modal>
  );
}
