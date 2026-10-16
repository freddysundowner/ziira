import { useState } from "react";

import { Alert, api, Button, Field, Modal, Select, toast, unwrap, useMutation, useQueryClient, useTranslation, type Schemas } from "@/sdk";

type Key = Schemas["ApiKeyOut"];

/** Replace a key: a new one is made with the same access, and the old one keeps working for the chosen overlap. */
export default function RotateDialog({ target, onClose, onRotated }: { target: Key | null; onClose: () => void; onRotated: (name: string, key: string) => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [hours, setHours] = useState("24");
  const rotate = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/api-keys/{key_id}/rotate", { params: { path: { key_id: target!.id } }, body: { grace_hours: Number(hours) } })),
    onSuccess: (made) => { void qc.invalidateQueries({ queryKey: ["api-keys"] }); onRotated(target!.name, made.key); },
    onError: (e) => toast(e.message, "bad"),
  });
  return (
    <Modal open={!!target} onClose={onClose} title={t("keys.rotateTitle", { name: target?.name })} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button loading={rotate.isPending} onClick={() => rotate.mutate()}>{t("keys.rotate")}</Button></>}>
      <div className="space-y-3">
        <p className="text-sm text-muted">{t("keys.rotateHint")}</p>
        <Field label={t("keys.overlap")}>
          <Select value={hours} onChange={(e) => setHours(e.target.value)}>
            {["0", "1", "24", "72", "168"].map((h) => <option key={h} value={h}>{h === "0" ? t("keys.overlapNone") : t("keys.overlapHours", { count: Number(h) })}</option>)}
          </Select>
        </Field>
        {hours === "0" && <Alert tone="warn">{t("keys.overlapNoneWarn")}</Alert>}
      </div>
    </Modal>
  );
}
