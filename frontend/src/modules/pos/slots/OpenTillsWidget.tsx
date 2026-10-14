import { Link } from "react-router-dom";

import { api, Skeleton, unwrap, useQuery, useTranslation } from "@/sdk";

import { useDeviceName } from "../hooks";

/** Home page box: the tills that are open right now. */
export default function OpenTillsWidget() {
  const { t } = useTranslation("pos");
  const deviceName = useDeviceName();
  const tills = useQuery({
    queryKey: ["pos-open-tills"], refetchInterval: 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/pos/tills", { params: { query: { status: "open", limit: 100 } } })),
  });
  if (tills.error) return <p role="alert" className="text-sm text-bad">{tills.error.message}</p>;
  if (!tills.data) return <Skeleton className="h-12 w-full" />;
  if (tills.data.length === 0) return <p className="text-sm text-muted">{t("noOpenTills")}</p>;
  return (
    <Link to="/pos/tills" className="block">
      <p className="tnum text-2xl font-semibold">{tills.data.length}</p>
      <p className="mt-1 truncate text-xs text-muted">{tills.data.slice(0, 3).map((x) => deviceName(x.device_id)).join(", ")}{tills.data.length > 3 ? "…" : ""}</p>
    </Link>
  );
}
