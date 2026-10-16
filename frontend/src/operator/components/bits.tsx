import { Check, Copy } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Link } from "react-router-dom";

import { Badge, Button, cx, toast, useTranslation } from "@/sdk";

import { INVOICE_TONES, STATUS_TONES, usedPercent } from "../helpers/format";

/** A subscription's state as a coloured, translated badge. */
export function SubscriptionBadge({ status }: { status: string }) {
  const { t } = useTranslation("operator");
  return <Badge tone={STATUS_TONES[status] ?? "neutral"}>{t(`status.${status}`, status)}</Badge>;
}

export function InvoiceBadge({ status }: { status: string }) {
  const { t } = useTranslation("operator");
  return <Badge tone={INVOICE_TONES[status] ?? "neutral"}>{t(`invoiceStatus.${status}`, status)}</Badge>;
}

/** Copies text and says so; if the browser refuses, says that instead. */
export function CopyButton({ text, label }: { text: string; label: string }) {
  const { t } = useTranslation("operator");
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      toast(t("common.copied"), "ok");
      setTimeout(() => setDone(false), 2000);
    } catch {
      toast(t("common.copyFailed"), "bad");
    }
  };
  return <Button size="sm" variant="secondary" onClick={() => void copy()}>{done ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />} {label}</Button>;
}

/** A list of counts as simple bars (tokens only). Each row can link somewhere. */
export function BarList({ items, empty }: { items: { key: string; label: string; value: number; to?: string }[]; empty: string }) {
  if (items.length === 0) return <p className="text-sm text-muted">{empty}</p>;
  const largest = Math.max(...items.map((i) => i.value), 1);
  return (
    <ul className="space-y-2">
      {items.map((i) => {
        const inner: ReactNode = (
          <>
            <div className="flex items-baseline justify-between gap-2 text-sm">
              <span className="truncate">{i.label}</span>
              <span className="tnum text-muted">{i.value}</span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-sunken" aria-hidden>
              <div className="h-full rounded-full bg-brand" style={{ width: `${Math.max(2, Math.round((i.value / largest) * 100))}%` }} />
            </div>
          </>
        );
        return <li key={i.key}>{i.to ? <Link to={i.to} className={cx("block rounded-md hover:bg-sunken/60")}>{inner}</Link> : inner}</li>;
      })}
    </ul>
  );
}

/** Number of items in a tab or card, quietly. */
export function Muted({ children }: { children: ReactNode }) {
  return <span className="text-xs text-muted">{children}</span>;
}

/** Used against a limit (empty limit = unlimited): a number and a bar that warns near the limit. */
export function Meter({ label, used, limit, unlimited }: { label: string; used: number; limit: number | null | undefined; unlimited: string }) {
  const percent = usedPercent(used, limit);
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span>{label}</span>
        <span className="tnum text-muted">{used} / {limit ?? unlimited}</span>
      </div>
      {limit ? (
        <div className="mt-1 h-2 overflow-hidden rounded-full bg-sunken" role="img" aria-label={`${label}: ${percent}%`}>
          <div className={cx("h-full rounded-full", percent >= 100 ? "bg-bad" : percent >= 80 ? "bg-warn" : "bg-brand")} style={{ width: `${Math.max(2, percent)}%` }} />
        </div>
      ) : null}
    </div>
  );
}
