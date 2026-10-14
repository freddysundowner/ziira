import { Copy, Download, Printer } from "lucide-react";
import { useState } from "react";

import { useTranslation } from "../i18n";
import { toast } from "../notify";
import { Alert, Button, Checkbox } from "../ui";
import { useUnsavedWarning } from "../ui/hooks";
import { copyText } from "./clipboard";

/** Prints the codes from a hidden frame, so nothing else on the page (and no address bar text) goes on the paper. */
function printCodes(title: string, note: string, codes: string[]): void {
  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
  document.body.appendChild(frame);
  const doc = frame.contentDocument;
  if (!doc) {
    frame.remove();
    return;
  }
  const escape = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
  doc.open();
  doc.write(
    `<!doctype html><title>${escape(title)}</title><body style="font-family:sans-serif"><h1>${escape(title)}</h1><p>${escape(note)}</p>` +
      `<ol style="font-family:monospace;font-size:20px;line-height:1.8">${codes.map((c) => `<li>${escape(c)}</li>`).join("")}</ol></body>`,
  );
  doc.close();
  frame.contentWindow?.focus();
  frame.contentWindow?.print();
  window.setTimeout(() => frame.remove(), 2000);
}

/** The backup codes, shown once, with copy, download and print, and a confirmation that they were kept somewhere safe. */
export function BackupCodes({ codes, onDone, doneLabel }: { codes: string[]; onDone: () => void; doneLabel?: string }) {
  const { t } = useTranslation();
  const [saved, setSaved] = useState(false);
  useUnsavedWarning(!saved);

  const copy = async () => toast(t((await copyText(codes.join("\n"))) ? "mfa.copied" : "mfa.copyFailed"), "ok");
  const download = () => {
    const blob = new Blob([`${t("mfa.fileHeader")}\n\n${codes.join("\n")}\n`], { type: "text/plain" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "ziira-backup-codes.txt";
    link.click();
    URL.revokeObjectURL(link.href);
  };

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">{t("mfa.backupTitle")}</h2>
        <p className="text-sm text-muted">{t("mfa.backupWhy")}</p>
      </div>
      <ul className="grid grid-cols-2 gap-2 rounded-xl border border-line bg-sunken p-3 font-mono text-sm" aria-label={t("mfa.backupTitle")}>
        {codes.map((c) => <li key={c} className="select-all text-center tracking-wide">{c}</li>)}
      </ul>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={() => void copy()}><Copy className="h-4 w-4" />{t("mfa.copyAll")}</Button>
        <Button size="sm" variant="secondary" onClick={download}><Download className="h-4 w-4" />{t("mfa.download")}</Button>
        <Button size="sm" variant="secondary" onClick={() => printCodes(t("mfa.backupTitle"), t("mfa.fileHeader"), codes)}><Printer className="h-4 w-4" />{t("mfa.print")}</Button>
      </div>
      <Alert tone="warn">{t("mfa.backupOnce")}</Alert>
      <Checkbox label={t("mfa.saved")} checked={saved} onChange={(e) => setSaved(e.target.checked)} />
      <Button size="lg" className="w-full" disabled={!saved} onClick={onDone}>{doneLabel ?? t("mfa.continue")}</Button>
    </div>
  );
}
