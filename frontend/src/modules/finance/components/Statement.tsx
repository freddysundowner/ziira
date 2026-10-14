import type { ReactNode } from "react";

import { cx, money, type Schemas } from "@/sdk";

export type StatementLine = Schemas["ProfitAndLossOut"]["income"][number];

/** Rows of a financial statement: a heading, its accounts, and an optional total row. Amounts are as the API returned them. */
export function StatementRows({ title, lines, total, totalLabel, currency, emphasis }: {
  title?: string; lines?: readonly StatementLine[]; total?: string; totalLabel?: string; currency?: string; emphasis?: "ok" | "bad" | "plain";
}) {
  return (
    <>
      {title && <tr className="bg-sunken/60"><th colSpan={2} scope="colgroup" className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted">{title}</th></tr>}
      {lines?.map((l) => (
        <tr key={l.account_id} className="border-t border-line">
          <td className="px-4 py-2"><span className="mr-2 font-mono text-xs text-muted">{l.code}</span>{l.name}</td>
          <td className="tnum px-4 py-2 text-right">{money(l.amount, currency)}</td>
        </tr>
      ))}
      {total !== undefined && (
        <tr className="border-t border-line font-semibold">
          <td className="px-4 py-2">{totalLabel}</td>
          <td className={cx("tnum px-4 py-2 text-right", emphasis === "ok" && "text-ok", emphasis === "bad" && "text-bad")}>{money(total, currency)}</td>
        </tr>
      )}
    </>
  );
}

export function StatementTable({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full text-sm"><tbody>{children}</tbody></table>
    </div>
  );
}
