import { Alert, Badge, DataTable, formatDate, money, useTranslation } from "@/sdk";

import { compactMoney, type Preview, REASON_ORDER, sampleColumns } from "../uploadLogic";

/** "We found 214 transactions from 3 Jan to 28 Feb 2026 ...", a few lines in plain words, and what to look at. */
export function Summary({ preview, currency, entityTitle }: { preview: Preview; currency?: string; entityTitle: string }) {
  const { t, i18n } = useTranslation("connect");
  const locale = i18n.language;
  const columns = sampleColumns(preview.fields);
  const figures = [
    preview.money_in !== null && { label: t("upload.moneyIn"), short: compactMoney(preview.money_in, currency, locale), exact: money(preview.money_in, currency) },
    preview.money_out !== null && { label: t("upload.moneyOut"), short: compactMoney(preview.money_out, currency, locale), exact: money(preview.money_out, currency) },
    preview.total !== null && { label: t("upload.totalIs"), short: compactMoney(preview.total, currency, locale), exact: money(preview.total, currency) },
  ].filter((f): f is { label: string; short: string; exact: string } => f !== false);
  const records = Object.values(preview.records).reduce((a, b) => a + b, 0);
  const count = preview.valid_rows;
  return (
    <div className="space-y-3">
      <div>
        <p className="text-lg font-semibold" role="status">
          {preview.first_moment && preview.last_moment
            ? t("upload.found", { count, what: entityTitle, from: formatDate(preview.first_moment), to: formatDate(preview.last_moment) })
            : t("upload.foundNoDates", { count, what: entityTitle })}
        </p>
        {figures.length > 0 && (
          <p className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {figures.map((f) => <span key={f.label} title={f.exact}>{f.label} <strong className="tnum">{f.short}</strong></span>)}
          </p>
        )}
        {records === 0 && preview.missing.length === 0 && <p className="mt-1 text-sm text-muted">{t("upload.nothingReadable")}</p>}
      </div>
      {preview.source === "scan" && <Alert tone="warn">{t("upload.fromPicture")}</Alert>}
      {preview.wrong_kind && <Alert tone="warn">{t("upload.wrongKind", { title: preview.wrong_kind.title })}</Alert>}
      {preview.missing.length > 0 && <Alert tone="bad">{t("upload.missing", { fields: preview.missing.join(", ") })}</Alert>}
      {preview.warnings.map((w) => <p key={w} className="text-xs text-muted">{w}</p>)}
      {columns.length > 0 && (
        <div>
          <p className="mb-1 text-sm font-medium">{t("upload.sample")}</p>
          <div className="overflow-hidden rounded-xl border border-line">
            <DataTable rows={preview.sample} rowKey={(r) => JSON.stringify(r)} dense empty={{ title: t("upload.noRows") }}
              columns={columns.map((c, i) => ({ header: c.label, hideBelow: i > 2 ? "sm" : undefined, align: ["money_in", "money_out", "amount", "total", "balance"].includes(c.name) ? "right" : undefined, cell: (r: Record<string, string>) => <span className={["money_in", "money_out", "amount", "total", "balance"].includes(c.name) ? "tnum" : ""}>{r[c.header] ?? ""}</span> }))} />
          </div>
        </div>
      )}
      {preview.check_reasons.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label={t("upload.pleaseCheck")}>
          {REASON_ORDER.filter((r) => preview.check_reasons.includes(r)).map((r) => <li key={r}><Badge tone="warn">{t(`upload.reason.${r}`)}</Badge></li>)}
        </ul>
      )}
    </div>
  );
}
