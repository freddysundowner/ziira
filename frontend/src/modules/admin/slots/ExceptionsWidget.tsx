import { Link } from "react-router-dom";

import { api, ErrorState, Skeleton, unwrap, useQuery, useTranslation } from "@/sdk";

const LIMIT = 100;

/** Dashboard box: exceptions still open in the branches the user manages. */
export default function ExceptionsWidget() {
  const { t } = useTranslation("kernel");
  const open = useQuery({ queryKey: ["exceptions-count"], queryFn: () => unwrap(api.GET("/api/v1/exceptions", { params: { query: { status: "open", limit: LIMIT } } })) });
  if (open.error) return <ErrorState title={t("widgetError")} message={open.error.message} onRetry={() => void open.refetch()} />;
  if (!open.data) return <Skeleton className="h-10 w-24" />;
  const count = open.data.length;
  const serious = open.data.filter((x) => x.severity === "high" || x.severity === "critical").length;
  return (
    <Link to="/admin/exceptions" className="block">
      <p className="tnum text-3xl font-semibold">{count >= LIMIT ? `${LIMIT}+` : count}</p>
      <p className="text-sm text-muted">{count === 0 ? t("widgetNoExceptions") : t("widgetExceptions", { count })}</p>
      {serious > 0 && <p className="mt-1 text-xs font-medium text-bad">{t("widgetSerious", { count: serious })}</p>}
    </Link>
  );
}
