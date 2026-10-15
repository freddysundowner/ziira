import { Link } from "react-router-dom";

import { Alert, api, Badge, Card, ErrorState, PageHeader, Skeleton, unwrap, useQuery, useTranslation } from "@/sdk";

import { OPENING_STEPS, stepStates } from "../lib/checklist";

/** A guide for moving a business onto Ziira: the imports in the order that works, with what each one needs and where it stands. */
export default function OpeningBalancesPage() {
  const { t } = useTranslation("imports");
  const kinds = useQuery({ queryKey: ["import-kinds"], queryFn: () => unwrap(api.GET("/api/v1/imports/kinds")) });
  const batches = useQuery({ queryKey: ["import-batches-all"], queryFn: () => unwrap(api.GET("/api/v1/imports/batches", { params: { query: { limit: 200 } } })) });
  const loading = kinds.isLoading || batches.isLoading;
  const failed = kinds.error ?? batches.error;
  const states = stepStates(kinds.data?.map((k) => k.kind) ?? [], batches.data ?? []);
  return (
    <>
      <PageHeader title={t("guide.title")} description={t("guide.hint")} back={{ to: "/imports", label: t("history") }} />
      <div className="mb-4"><Alert tone="info"><strong className="font-medium">{t("guide.before")}</strong> {t("guide.beforeHint")}</Alert></div>
      {loading ? <Skeleton className="h-64 w-full" /> : failed ? (
        <ErrorState message={failed.message} onRetry={() => { void kinds.refetch(); void batches.refetch(); }} />
      ) : (
        <ol className="space-y-3">
          {OPENING_STEPS.map((step, index) => {
            const state = states[step.id];
            const target = step.kind ? `/imports/new?kind=${step.kind}` : step.link;
            return (
              <li key={step.id}>
                <Card>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium"><span className="tnum mr-2 text-muted">{index + 1}.</span>{t(`guide.steps.${step.id}.title`)}</p>
                      <p className="mt-1 text-sm text-muted">{t(`guide.steps.${step.id}.text`)}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {state === "done" && <Badge tone="ok">{t("guide.done")}</Badge>}
                      {state === "unavailable" && <Badge>{t("guide.unavailable")}</Badge>}
                      {state !== "unavailable" && target && (
                        <Link to={target} className="inline-flex h-9 items-center rounded-lg border border-line px-3 text-sm font-medium hover:bg-sunken">
                          {step.kind ? t("guide.import") : t("guide.open")}
                        </Link>
                      )}
                    </div>
                  </div>
                </Card>
              </li>
            );
          })}
        </ol>
      )}
    </>
  );
}
