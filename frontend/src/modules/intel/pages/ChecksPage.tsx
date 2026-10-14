import { api, Card, ErrorState, PageHeader, SkeletonRows, unwrap, useQuery, useTranslation } from "@/sdk";

import { useAreaLabel } from "../components/Badges";
import CheckCard from "../components/CheckCard";
import RunChecks from "../components/RunChecks";
import { groupChecks } from "../logic";

export default function ChecksPage() {
  const { t } = useTranslation("intel");
  const areaLabel = useAreaLabel();
  const checks = useQuery({ queryKey: ["intel", "checks"], queryFn: () => unwrap(api.GET("/api/v1/intel/checks")) });
  return (
    <>
      <PageHeader title={t("checksTitle")} description={t("checksHint")} back={{ to: "/findings", label: t("title") }} />
      <div className="space-y-4">
        <RunChecks />
        {checks.error ? <ErrorState message={checks.error.message} onRetry={() => void checks.refetch()} />
          : !checks.data ? <SkeletonRows rows={6} cols={2} />
            : groupChecks(checks.data).map((g) => (
              <Card key={g.area} title={areaLabel(g.area)} description={t("checkCount", { count: g.checks.length })}>
                <div className="divide-y divide-line">{g.checks.map((c) => <CheckCard key={`${c.code}-${JSON.stringify(c.params)}-${c.enabled}`} check={c} />)}</div>
              </Card>
            ))}
      </div>
    </>
  );
}
