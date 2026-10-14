import { formatDate, humanise, money, Schemas, useTranslation } from "@/sdk";

import { Row, Rule, Sheet } from "./PrintArea";

type Report = Schemas["TillReportOut"];

/** The end-of-day report for one till: X while it is open, Z once it is closed. Prints on a till roll. */
export function ZReportSheet({ report, currency, heading, lines, closedAt }: {
  report: Report; currency?: string; heading: string[]; lines: [string, string][]; closedAt?: string | null;
}) {
  const { t } = useTranslation("pos");
  const m = (v: string | null | undefined) => money(v, currency);
  const closed = report.status === "closed";
  return (
    <Sheet>
      {heading.map((h, i) => <p key={i} className={i === 0 ? "text-center text-sm font-bold" : "text-center"}>{h}</p>)}
      <Rule />
      <p className="text-center font-bold uppercase">{closed ? t("zReport") : t("xReport")}</p>
      <Row left={t("businessDate")} right={formatDate(report.business_date)} />
      {lines.map(([label, value]) => <Row key={label} left={label} right={value} />)}
      {closedAt && <Row left={t("closedAt")} right={formatDate(closedAt, true)} />}
      <Rule />
      <Row left={t("salesCount")} right={report.sales_count} />
      <Row left={t("salesTotal")} right={m(report.sales_total)} strong />
      <Row left={t("taxIncluded")} right={m(report.tax_total)} />
      <Row left={t("discountsGiven")} right={m(report.discount_total)} />
      <Row left={`${t("voided")} (${report.voided_count})`} right={m(report.voided_total)} />
      <Rule />
      <p className="font-bold">{t("takingsByMethod")}</p>
      {Object.entries(report.takings_by_method).map(([method, amount]) => <Row key={method} left={t(`methods.${method}`, humanise(method))} right={m(amount)} />)}
      <Rule />
      <Row left={t("openingFloat")} right={m(report.opening_float)} />
      <Row left={t("cashRefunded")} right={m(report.cash_refunded)} />
      <Row left={t("expectedCash")} right={m(report.expected_cash)} strong />
      {closed && (
        <>
          <Row left={t("countedCash")} right={m(report.counted_cash)} />
          <Row left={t("variance")} right={m(report.variance)} strong />
        </>
      )}
    </Sheet>
  );
}
