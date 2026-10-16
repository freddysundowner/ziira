import { api, Button, Card, EmptyState, ErrorState, formatDate, SkeletonRows, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

import { usePlain } from "../usePlain";

/** What the business has told Ziira is normal ("ignore this at Ruiru for 30 days"), each with a way to take it back. */
export default function IgnoreRules() {
  const { t } = useTranslation("intel");
  const qc = useQueryClient();
  const plain = usePlain();
  const q = useQuery({ queryKey: ["intel", "ignore-rules"], queryFn: () => unwrap(api.GET("/api/v1/intel/ignore-rules")) });
  const remove = useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/v1/intel/ignore-rules/{rule_id}", { params: { path: { rule_id: id } } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["intel", "ignore-rules"] }); toast(t("ignoreRules.removed"), "ok"); },
  });
  return (
    <Card title={t("ignoreRules.title")} description={t("ignoreRules.hint")}>
      {q.error ? <ErrorState message={q.error.message} onRetry={() => void q.refetch()} /> : !q.data ? <SkeletonRows rows={2} cols={2} /> : q.data.length === 0 ? (
        <EmptyState title={t("ignoreRules.none")} hint={t("ignoreRules.noneHint")} />
      ) : (
        <ul className="divide-y divide-line">
          {q.data.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-3 first:pt-0 last:pb-0">
              <div className="min-w-0 text-sm">
                <p className="font-medium">{plain.check(r.check_code)?.title ?? r.check_code}</p>
                <p className="text-muted">
                  {r.scope_label ? t("ignoreRules.at", { where: r.scope_label }) : t("ignoreRules.everywhere")} · {r.until_date ? t("ignoreRules.until", { date: formatDate(r.until_date) }) : t("ignoreRules.always")}
                  {r.created_by_name ? ` · ${t("ignoreRules.by", { who: r.created_by_name, date: formatDate(r.created_at) })}` : ""}
                </p>
              </div>
              <Button size="sm" variant="secondary" loading={remove.isPending && remove.variables === r.id} onClick={() => remove.mutate(r.id)}>{t("ignoreRules.remove")}</Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
