import { Search } from "lucide-react";

import { api, Alert, Badge, Button, Checkbox, humanise, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { groupBySource, isFinished, type PrivacyRequest } from "./model";

/** Step 1: ask every unit what it holds. Records found by name are only "possible" until a person confirms them. */
export default function SearchStep({ request, confirmed, onToggle, canEdit }: {
  request: PrivacyRequest; confirmed: ReadonlySet<string>; onToggle: (recordId: string, on: boolean) => void; canEdit: boolean;
}) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const search = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/privacy/requests/{request_id}/search", { params: { path: { request_id: request.id } } })),
    onSuccess: (r) => {
      qc.setQueryData(["privacy-request", request.id], r);
      void qc.invalidateQueries({ queryKey: ["privacy-requests"] });
      toast(t("dsr.search.done", { count: r.found.length }), "ok");
    },
  });
  const groups = groupBySource(request.found);
  const searched = request.found.length > 0 || request.status !== "open";
  const finished = isFinished(request);

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">{t("dsr.search.intro")}</p>
      {!finished && canEdit && (
        <Button variant={searched ? "secondary" : "primary"} loading={search.isPending} onClick={() => search.mutate()}>
          <Search className="h-4 w-4" />{searched ? t("dsr.search.again") : t("dsr.search.run")}
        </Button>
      )}
      {searched && groups.length === 0 && <Alert tone="info">{t("dsr.search.nothing")}</Alert>}
      {groups.some((g) => g.possible > 0) && !finished && <Alert tone="warn">{t("dsr.search.possibleWarning")}</Alert>}
      <div className="space-y-3">
        {groups.map((g) => (
          <section key={g.source} className="rounded-lg border border-line">
            <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-sunken/50 px-3 py-2">
              <h3 className="text-sm font-semibold">{t(`dsr.source.${g.source}`, { defaultValue: humanise(g.source) })}</h3>
              <span className="text-xs text-muted">{t("dsr.search.groupCount", { exact: g.exact, possible: g.possible })}</span>
            </header>
            <ul className="divide-y divide-line">
              {g.records.map((r) => (
                <li key={r.record_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{r.label}</p>
                    <p className="text-xs text-muted">{humanise(r.kind)}</p>
                  </div>
                  {r.match === "exact"
                    ? <Badge tone="ok">{t("dsr.exact")}</Badge>
                    : <Badge tone="warn">{t("dsr.possible")}</Badge>}
                  {r.match === "possible" && !finished && canEdit && (
                    <Checkbox label={t("dsr.search.include")} checked={confirmed.has(r.record_id)} onChange={(e) => onToggle(r.record_id, e.target.checked)} />
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
