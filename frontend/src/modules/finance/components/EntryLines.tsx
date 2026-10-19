import { DataTable, money, useTranslation } from "@/sdk";

import { branchName, type Scope } from "../scope";

interface Line {
  account_id: string;
  branch_id: string | null;
  debit: string;
  credit: string;
  description: string | null;
}

/** The lines of an entry or journal with account names, and the debit / credit totals underneath. */
export function EntryLines({ lines, names, scope, currency }: { lines: readonly Line[]; names: Map<string, string>; scope: Scope; currency?: string }) {
  const { t } = useTranslation("finance");
  const sum = (key: "debit" | "credit") => lines.reduce((s, l) => s + Math.round(Number(l[key]) * 100), 0) / 100;
  return (
    <DataTable dense rows={lines} rowKey={(l) => `${l.account_id}-${l.debit}-${l.credit}-${l.description}-${l.branch_id}-${lines.indexOf(l)}`} empty={{ title: t("noLines") }}
      columns={[
        { header: t("account"), cell: (l) => <span className="font-medium">{names.get(l.account_id) ?? "…"}</span> },
        { header: t("branch"), hideBelow: "md", cell: (l) => (l.branch_id ? branchName(scope, l.branch_id) : "—") },
        { header: t("description"), hideBelow: "lg", cell: (l) => l.description ?? "—" },
        { header: t("debit"), align: "right", cell: (l) => (Number(l.debit) ? money(l.debit, currency) : "") },
        { header: t("credit"), align: "right", cell: (l) => (Number(l.credit) ? money(l.credit, currency) : "") },
      ]}
      footer={
        <div className="tnum flex flex-wrap justify-end gap-x-6 gap-y-1 border-t border-line px-4 py-2.5 text-sm font-semibold">
          <span>{t("totals")}</span><span>{money(sum("debit"), currency)}</span><span>{money(sum("credit"), currency)}</span>
        </div>}
    />
  );
}
