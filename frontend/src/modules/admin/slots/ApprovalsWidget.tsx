import { Link } from "react-router-dom";

import { api, ErrorState, Skeleton, type SlotProps, unwrap, useQuery, useTranslation } from "@/sdk";

/** Dashboard box: requests waiting for the signed-in user's approval. */
export default function ApprovalsWidget({ variant }: SlotProps) {
  const { t } = useTranslation("kernel");
  const pending = useQuery({ queryKey: ["approvals-pending"], queryFn: () => unwrap(api.GET("/api/v1/approvals/pending")) });
  if (pending.error) return <ErrorState title={t("widgetError")} message={pending.error.message} onRetry={() => void pending.refetch()} />;
  if (!pending.data) return <Skeleton className="h-10 w-24" />;
  const count = pending.data.length;
  if (count === 0 && variant !== "stat") return <Link to="/admin/approvals" data-clear className="block text-sm text-muted">{t("widgetNoApprovals")}</Link>;
  return (
    <Link to="/admin/approvals" className="block">
      <p className="tnum text-3xl font-semibold">{count}</p>
      <p className="text-sm text-muted">{count === 0 ? t("widgetNoApprovals") : t("widgetApprovals", { count })}</p>
    </Link>
  );
}
