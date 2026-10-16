import { Alert, Button, Modal, useTranslation } from "@/sdk";

import { CopyButton } from "./bits";

/**
 * A temporary password for a new or reset operator. It is shown once, here: it is given to that person, who must
 * choose their own at the first sign-in. Nothing here is kept after the box is closed.
 */
export function TemporaryPasswordDialog({ name, password, onClose }: { name: string; password: string; onClose: () => void }) {
  const { t } = useTranslation("operator");
  return (
    <Modal open onClose={onClose} title={t("operators.tempTitle", { name })} size="sm" footer={<Button onClick={onClose}>{t("operators.secretSaved")}</Button>}>
      <div className="space-y-4 text-sm">
        <Alert tone="warn">{t("operators.tempWarning")}</Alert>
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">{t("operators.tempLabel")}</p>
          <p className="break-all rounded-lg bg-sunken px-3 py-2 font-mono text-sm" data-testid="temp-password">{password}</p>
          <div className="mt-2"><CopyButton text={password} label={t("operators.copyPassword")} /></div>
        </div>
      </div>
    </Modal>
  );
}
