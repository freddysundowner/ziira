import { Alert, api, Button, Card, toast, unwrap, useCompany, useMutation, useQueryClient, useTranslation } from "@/sdk";
import type { Schemas } from "@/sdk";
import { useState } from "react";

type Run = Schemas["ziira__modules__intel__api__schemas__RunOut"];

/** "Run checks now" for each company, with what the run created, updated and resolved. */
export default function RunChecks() {
  const { t } = useTranslation("intel");
  const qc = useQueryClient();
  const { companies } = useCompany();
  const [results, setResults] = useState<Record<string, Run>>({});
  const run = useMutation({
    mutationFn: (companyId: string) => unwrap(api.POST("/api/v1/intel/run", { body: { company_id: companyId } })).then((r) => [companyId, r] as const),
    onSuccess: ([companyId, r]) => {
      setResults((all) => ({ ...all, [companyId]: r }));
      void qc.invalidateQueries({ queryKey: ["intel", "findings"] });
      void qc.invalidateQueries({ queryKey: ["intel", "summary"] });
      toast(t("runDone"), "ok");
    },
  });

  return (
    <Card title={t("runTitle")} description={t("runHint")}>
      <div className="space-y-3">
        {companies.map((c) => {
          const r = results[c.id];
          return (
            <div key={c.id} className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                {companies.length > 1 && <span className="text-sm font-medium">{c.name}</span>}
                <Button variant="secondary" loading={run.isPending && run.variables === c.id} disabled={run.isPending} onClick={() => run.mutate(c.id)}>{t("runNow")}</Button>
              </div>
              {r && (
                <Alert tone={r.failed.length ? "warn" : "ok"}>
                  {t("runResult", { run: r.checks_run, created: r.created, updated: r.updated, resolved: r.resolved, reopened: r.reopened })}
                  {r.failed.length > 0 && <> {t("runFailed", { checks: r.failed.join(", ") })}</>}
                </Alert>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
