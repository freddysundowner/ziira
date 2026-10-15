import { AlertTriangle, CloudOff } from "lucide-react";
import { useState } from "react";

import { Button, useTranslation } from "@/sdk";

import { useOutbox } from "../offline/hooks";
import { QueueDialog } from "./QueueDialog";

/** A slim strip under the terminal bar when something needs the cashier's eye: no connection, sales needing attention, an old or large queue, no way to store sales. */
export function SyncBanner() {
  const { t } = useTranslation("pos");
  const { online, counts, warnings, storageOk, ready } = useOutbox();
  const [open, setOpen] = useState(false);
  const lines: { key: string; tone: "warn" | "bad"; text: string }[] = [];
  if (ready && !storageOk) lines.push({ key: "storage", tone: "bad", text: t("terminal.sync.noStorage") });
  if (!online && storageOk) lines.push({ key: "offline", tone: "warn", text: t("terminal.sync.offlineBanner") });
  if (counts.attention > 0) lines.push({ key: "attention", tone: "bad", text: t("terminal.sync.attentionBanner", { count: counts.attention }) });
  if (warnings.includes("old")) lines.push({ key: "old", tone: "warn", text: t("terminal.sync.oldWarning") });
  if (warnings.includes("large")) lines.push({ key: "large", tone: "warn", text: t("terminal.sync.largeWarning", { count: counts.waiting + counts.attention }) });
  if (lines.length === 0) return null;
  return (
    <div className="no-print shrink-0 divide-y divide-line border-b border-line" data-testid="sync-banner">
      {lines.map((l) => (
        <div key={l.key} role={l.tone === "bad" ? "alert" : "status"}
          className={`flex items-center gap-2 px-3 py-1.5 text-xs font-medium ${l.tone === "bad" ? "bg-bad-soft text-bad" : "bg-warn-soft text-warn"}`}>
          {l.tone === "bad" ? <AlertTriangle className="h-3.5 w-3.5 shrink-0" /> : <CloudOff className="h-3.5 w-3.5 shrink-0" />}
          <span className="min-w-0 flex-1">{l.text}</span>
          {(counts.waiting > 0 || counts.attention > 0) && l.key !== "storage" && <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>{t("terminal.sync.viewQueue")}</Button>}
        </div>
      ))}
      {open && <QueueDialog onClose={() => setOpen(false)} />}
    </div>
  );
}
