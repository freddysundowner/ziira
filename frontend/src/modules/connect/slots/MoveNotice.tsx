import { Link } from "react-router-dom";

import { api, Button, unwrap, useCompany, useQuery, useTranslation } from "@/sdk";

/** On Add-ons: once Core units are switched on and a connected system has data to bring over, say so. */
export default function MoveNotice() {
  const { t } = useTranslation("connect");
  const { company } = useCompany();
  const suggestion = useQuery({
    queryKey: ["connect", "move-suggestion", company?.id], enabled: !!company,
    queryFn: () => unwrap(api.GET("/api/v1/connect/move/suggestion", { params: { query: { company_id: company!.id } } })),
  });
  if (!suggestion.data?.suggest) return null;
  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-brand-soft p-4">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-brand-strong">{t("move.suggest.title")}</p>
        <p className="text-xs text-muted">{t("move.suggest.hint")}</p>
      </div>
      <Link to={`/connect/connections/${suggestion.data.connection_id}/move`}><Button>{t("move.suggest.action")}</Button></Link>
    </div>
  );
}
