import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Alert, Button, Input, Modal, useTranslation } from "@/sdk";

/** Shows a signing secret once. After this it cannot be read again. */
export default function SecretReveal({ secret, onClose }: { secret: { name: string; value: string } | null; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(secret!.value); setCopied(true); } catch { setCopied(false); }
  };
  const close = () => { setCopied(false); onClose(); };
  return (
    <Modal open={!!secret} onClose={close} title={t("webhooks.secretTitle", { name: secret?.name })} footer={<Button onClick={close}>{t("savedIt")}</Button>}>
      <div className="space-y-3">
        <Alert tone="warn">{t("webhooks.secretWarning")}</Alert>
        <div className="flex gap-2">
          <Input readOnly aria-label={t("webhooks.secret")} value={secret?.value ?? ""} className="font-mono text-xs" onFocus={(e) => e.target.select()} />
          <Button variant="secondary" onClick={() => void copy()}>{copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}{copied ? t("copied") : t("copy")}</Button>
        </div>
        <p className="text-xs text-muted">{t("webhooks.secretUse")}</p>
      </div>
    </Modal>
  );
}
