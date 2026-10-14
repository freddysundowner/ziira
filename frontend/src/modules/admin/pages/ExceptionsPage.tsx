import { useState } from "react";

import {
  api, Badge, DataTable, formatDate, humanise, Input, money, Pager, PageHeader, Select, StatusBadge, unwrap, useCurrency, useDebounced,
  usePagedList, useTranslation,
} from "@/sdk";

import ExceptionDrawer from "./exceptions/ExceptionDrawer";
import { EXCEPTION_STATUSES, SEVERITY_TONE } from "./exceptions/constants";

/** Things that need a person's attention, raised by any unit. */
export default function ExceptionsPage() {
  const { t } = useTranslation("kernel");
  const [status, setStatus] = useState("open");
  const [unit, setUnit] = useState("");
  const unitFilter = useDebounced(unit.trim());
  const [openId, setOpenId] = useState<string | null>(null);
  const list = usePagedList(["exceptions", status, unitFilter], (limit, offset) =>
    unwrap(api.GET("/api/v1/exceptions", { params: { query: { status: status || undefined, unit: unitFilter || undefined, limit, offset } } })));
  const currency = useCurrency();

  return (
    <>
      <PageHeader title={t("exceptions")} description={t("exceptionsHint")} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(x) => x.id}
        toolbar={
          <>
            <Select aria-label={t("status")} className="w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>
              {EXCEPTION_STATUSES.map((s) => <option key={s} value={s}>{t(`exStatus.${s}`)}</option>)}
            </Select>
            <Input aria-label={t("unit")} className="w-40" placeholder={t("unit")} value={unit} onChange={(e) => setUnit(e.target.value)} />
          </>
        }
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
        empty={{ title: status === "open" ? t("noOpenExceptions") : t("noExceptions"), hint: status === "open" ? t("noOpenExceptionsHint") : undefined }}
        columns={[
          { header: t("severity"), cell: (x) => <Badge tone={SEVERITY_TONE[x.severity] ?? "neutral"}>{t(`severityName.${x.severity}`, { defaultValue: humanise(x.severity) })}</Badge> },
          { header: t("what"), cell: (x) => <button className="text-left hover:underline" onClick={() => setOpenId(x.id)}><span className="font-medium">{humanise(x.kind)}</span><span className="block max-w-md truncate text-xs text-muted">{x.message}</span></button> },
          { header: t("unit"), hideBelow: "md", cell: (x) => humanise(x.unit_name) },
          { header: t("amount"), hideBelow: "lg", align: "right", cell: (x) => (x.amount == null ? "—" : money(x.amount, currency)) },
          { header: t("raised"), hideBelow: "sm", cell: (x) => formatDate(x.created_at, true) },
          { header: t("status"), cell: (x) => <StatusBadge status={x.status} /> },
        ]}
      />
      <ExceptionDrawer id={openId} onClose={() => setOpenId(null)} />
    </>
  );
}
