import { Link } from "react-router-dom";

import { api, Badge, Button, unwrap, useCan, useCompany, useQuery, useTranslation } from "@/sdk";

/** Home box: with nothing connected, the first step; otherwise how the connections are doing. */
export default function ConnectWidget() {
  const { t } = useTranslation("connect");
  const canManage = useCan("connect.manage");
  const { company } = useCompany();
  const suggestion = useQuery({
    queryKey: ["connect", "move-suggestion", company?.id], enabled: !!company && canManage,
    queryFn: () => unwrap(api.GET("/api/v1/connect/move/suggestion", { params: { query: { company_id: company!.id } } })), refetchInterval: 300_000,
  });
  const list = useQuery({ queryKey: ["connect", "connections"], queryFn: () => unwrap(api.GET("/api/v1/connect/connections")), refetchInterval: 60_000 });
  if (list.error) return <p className="text-sm text-bad">{list.error.message} <button className="underline" onClick={() => void list.refetch()}>{t("retry")}</button></p>;
  if (!list.data) return <p className="text-sm text-muted">{t("loading")}</p>;
  const live = list.data.filter((c) => c.status !== "disconnected");
  if (live.length === 0) {
    return (
      <div className="space-y-2">
        <p className="font-medium">{t("first.title")}</p>
        <p className="text-sm text-muted">{t("first.hint")}</p>
        {canManage && <Link to="/connect/new"><Button>{t("connectFirst")}</Button></Link>}
      </div>
    );
  }
  const broken = live.filter((c) => c.status === "error").length;
  const move = suggestion.data?.suggest ? suggestion.data.connection_id : null;
  return (
    <div className="space-y-3">
      <Link to="/connect" className="block space-y-1">
        <p className="tnum text-2xl font-semibold">{t("widget.connected", { count: live.length })}</p>
        {broken > 0 ? <Badge tone="bad">{t("widget.broken", { count: broken })}</Badge> : <Badge tone="ok">{t("widget.fine")}</Badge>}
      </Link>
      {move && (
        <div className="space-y-2 rounded-lg bg-brand-soft p-3">
          <p className="text-sm font-medium text-brand-strong">{t("move.suggest.title")}</p>
          <p className="text-xs text-muted">{t("move.suggest.hint")}</p>
          <Link to={`/connect/connections/${move}/move`}><Button size="sm">{t("move.suggest.action")}</Button></Link>
        </div>
      )}
    </div>
  );
}
