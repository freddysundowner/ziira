import { useState } from "react";

import { api, Card, EmptyState, ErrorState, SkeletonRows, toast, unwrap, useCan, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

import ActionLog from "./ActionLog";
import LevelPicker from "./LevelPicker";
import RulesSection from "./RulesSection";

/** How much Ziira does for you: the four ways it can work, the things it may do by itself (the last way), and what it did. */
export default function ActionsSettings({ companyId }: { companyId: string | undefined }) {
  const { t } = useTranslation("intel");
  const qc = useQueryClient();
  const canManage = useCan("findings.manage");
  const key = ["company-settings", companyId];
  const [problem, setProblem] = useState<string | null>(null);
  const settings = useQuery({
    enabled: !!companyId, queryKey: key,
    queryFn: () => unwrap(api.GET("/api/v1/companies/{company_id}/settings", { params: { path: { company_id: companyId! } } })),
  });
  const change = useMutation({
    meta: { silent: true },
    mutationFn: (level: number) => unwrap(api.PATCH("/api/v1/companies/{company_id}/settings", { params: { path: { company_id: companyId! } }, body: { intel_action_level: level } })),
    onSuccess: (data) => {
      setProblem(null);
      qc.setQueryData(key, data);
      void qc.invalidateQueries({ queryKey: ["intel", "proposals"] });
      toast(t("how.saved", { name: t(`how.mode.${data.intel_action_level}.name`) }), "ok");
    },
    onError: (e) => { setProblem(e.message); toast(e.message, "bad"); },
  });

  if (!companyId) return <EmptyState title={t("how.noCompany")} />;
  if (settings.error) return <ErrorState message={settings.error.message} onRetry={() => void settings.refetch()} />;
  if (!settings.data) return <SkeletonRows rows={5} cols={2} />;
  const level = settings.data.intel_action_level;

  return (
    <div className="space-y-4">
      <Card title={t("how.title")} description={t("how.hint")}>
        <LevelPicker level={level} busy={change.isPending} error={problem} onChange={(n) => change.mutate(n)} />
      </Card>
      {canManage && <RulesSection companyId={companyId} level={level} />}
      {canManage && <ActionLog companyId={companyId} />}
    </div>
  );
}
