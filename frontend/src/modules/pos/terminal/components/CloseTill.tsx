import { Printer } from "lucide-react";
import { useState } from "react";

import {
  Alert, api, Button, DetailList, ErrorState, Field, humanise, Input, Modal, money, NumberInput, Select, SkeletonRows, StatusBadge, unwrap, useMutation, useQuery,
  useTranslation, type Schemas,
} from "@/sdk";

import { num, text } from "../cart";
import { PrintStyles } from "./Receipt";

/** End the shift: see what the till should hold, count the drawer, explain any difference, close. */
export function CloseTill({ till, currency, blockedBy, heldCount, onClose, onClosed }: {
  till: Schemas["TillOut"]; currency: string; blockedBy: boolean; heldCount: number; onClose: () => void; onClosed: () => void;
}) {
  const { t } = useTranslation("pos");
  const [counted, setCounted] = useState("");
  const [reasonId, setReasonId] = useState("");
  const [note, setNote] = useState("");
  const [closed, setClosed] = useState<Schemas["TillReportOut"] | null>(null);

  const report = useQuery({
    queryKey: ["pos-terminal", "till-report", till.id],
    queryFn: () => unwrap(api.GET("/api/v1/pos/tills/{till_id}/report", { params: { path: { till_id: till.id } } })),
  });
  const difference = report.data && counted !== "" ? Math.round((num(counted) - num(report.data.expected_cash)) * 100) / 100 : 0;
  const reasons = useQuery({
    enabled: difference !== 0,
    queryKey: ["pos-terminal", "reasons", "till_variance"],
    queryFn: () => unwrap(api.GET("/api/v1/settings/reason-codes", { params: { query: { category: "till_variance" } } })),
  });

  const close = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/pos/tills/{till_id}/close", {
      params: { path: { till_id: till.id } },
      body: { counted_cash: counted, reason_code_id: difference !== 0 ? reasonId : null, note: note.trim() || null },
    })),
    // The terminal stays on screen until the cashier has seen the Z report; the caller refreshes the till list when this closes.
    onSuccess: setClosed,
  });

  if (closed) return <ZReport report={closed} currency={currency} onDone={onClosed} />;

  const ready = counted !== "" && !blockedBy && (difference === 0 || !!reasonId);
  return (
    <Modal open onClose={close.isPending ? () => undefined : onClose} title={t("terminal.close.title")} size="md"
      footer={<><Button variant="secondary" onClick={onClose} disabled={close.isPending}>{t("terminal.cancel")}</Button>
        <Button variant="danger" loading={close.isPending} disabled={!ready || !report.data} onClick={() => close.mutate()}>{close.error ? t("terminal.retry") : t("terminal.close.submit")}</Button></>}>
      {report.isLoading ? <SkeletonRows rows={5} cols={1} />
        : report.error ? <ErrorState message={report.error.message} onRetry={() => void report.refetch()} />
        : report.data && (
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (ready) close.mutate(); }}>
            {blockedBy && <Alert tone="warn">{t("terminal.close.cartOpen")}</Alert>}
            {heldCount > 0 && <Alert tone="warn">{t("terminal.close.heldLost", { count: heldCount })}</Alert>}
            <Figures report={report.data} currency={currency} />
            <Field label={t("terminal.close.counted")} hint={t("terminal.close.countedHint")}>
              <NumberInput value={counted} onChange={setCounted} autoFocus data-autofocus />
            </Field>
            {counted !== "" && (
              <div className="flex items-center justify-between rounded-lg bg-sunken px-3 py-2 text-sm">
                <span className="text-muted">{t("terminal.close.variance")}</span>
                <span className={`tnum font-semibold ${difference === 0 ? "text-ok" : "text-bad"}`}>
                  {difference === 0 ? t("terminal.close.balanced") : `${difference > 0 ? "+" : ""}${money(text(difference), currency)} ${difference > 0 ? t("terminal.close.over") : t("terminal.close.short")}`}
                </span>
              </div>
            )}
            {difference !== 0 && (
              <>
                <Field label={t("terminal.close.reason")} required>
                  <Select value={reasonId} onChange={(e) => setReasonId(e.target.value)}>
                    <option value="">{t("terminal.close.chooseReason")}</option>
                    {reasons.data?.filter((r) => r.is_active).map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
                  </Select>
                </Field>
                <Field label={t("terminal.close.note")}><Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} /></Field>
              </>
            )}
            <p className="text-xs text-muted">{t("terminal.close.final")}</p>
            {close.error && <Alert tone="bad">{close.error.message}</Alert>}
            <button type="submit" className="hidden" />
          </form>
        )}
    </Modal>
  );
}

function Figures({ report, currency }: { report: Schemas["TillReportOut"]; currency: string }) {
  const { t } = useTranslation("pos");
  return (
    <DetailList items={[
      { label: t("terminal.close.float"), value: money(report.opening_float, currency) },
      { label: t("terminal.close.sales"), value: `${report.sales_count} · ${money(report.sales_total, currency)}` },
      ...Object.entries(report.takings_by_method).map(([method, amount]) => ({ label: humanise(method), value: money(amount, currency) })),
      { label: t("terminal.close.refunded"), value: money(report.cash_refunded, currency) },
      { label: t("terminal.close.voided"), value: `${report.voided_count} · ${money(report.voided_total, currency)}` },
      { label: t("terminal.close.expected"), value: <strong>{money(report.expected_cash, currency)}</strong> },
    ]} />
  );
}

function ZReport({ report, currency, onDone }: { report: Schemas["TillReportOut"]; currency: string; onDone: () => void }) {
  const { t } = useTranslation("pos");
  return (
    <Modal open onClose={onDone} title={t("terminal.close.closedTitle")} size="md"
      footer={<><Button variant="secondary" onClick={() => window.print()}><Printer className="h-4 w-4" />{t("terminal.close.print")}</Button><Button onClick={onDone} autoFocus>{t("terminal.close.done")}</Button></>}>
      <div id="pos-receipt" className="space-y-3">
        <PrintStyles />
        <div className="flex items-center justify-between"><span className="text-sm text-muted">{report.business_date}</span><StatusBadge status={report.status} /></div>
        <Figures report={report} currency={currency} />
        <DetailList items={[
          { label: t("terminal.close.countedDone"), value: money(report.counted_cash, currency) },
          { label: t("terminal.close.variance"), value: money(report.variance, currency) },
        ]} />
      </div>
    </Modal>
  );
}
