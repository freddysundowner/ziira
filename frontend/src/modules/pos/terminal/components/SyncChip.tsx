import { AlertTriangle, Loader2, Wifi, WifiOff } from "lucide-react";
import { useState } from "react";

import { Badge, type BadgeTone, useTranslation } from "@/sdk";

import { useOutbox } from "../offline/hooks";
import { QueueDialog } from "./QueueDialog";

const TONE: Record<string, BadgeTone> = { online: "ok", offline: "warn", syncing: "info", waiting: "warn", attention: "bad" };

/** The terminal's connection and sales-queue status, always in the bar. Tap it for the list of sales waiting. */
export function SyncChip() {
  const { t } = useTranslation("pos");
  const { chip, counts, online } = useOutbox();
  const [open, setOpen] = useState(false);
  const Icon = chip.kind === "attention" ? AlertTriangle : chip.kind === "syncing" ? Loader2 : online ? Wifi : WifiOff;
  const label = t(`terminal.sync.chip.${chip.kind}`, { count: chip.n });
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} data-testid="sync-chip" data-state={chip.kind} aria-label={t("terminal.sync.open")}
        className="inline-flex h-10 shrink-0 items-center rounded-lg px-1 hover:bg-sunken">
        <Badge tone={TONE[chip.kind] ?? "neutral"}>
          <Icon className={chip.kind === "syncing" ? "h-3 w-3 animate-spin" : "h-3 w-3"} />
          {label}
          {chip.kind === "offline" && counts.waiting > 0 && <span> · {t("terminal.sync.chip.waiting", { count: counts.waiting })}</span>}
        </Badge>
      </button>
      {open && <QueueDialog onClose={() => setOpen(false)} />}
    </>
  );
}
