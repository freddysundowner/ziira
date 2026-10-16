import { Alert, api, Button, toast, unwrap, useCan, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

/**
 * Shown where findings are read: when Ziira Core now runs the same ground as a connected system, the connected system's
 * checks stay quiet there, and the business can pause the connection or keep both. Quiet when nothing overlaps.
 */
export function OverlapBanner({ companyId, compact }: { companyId: string; compact?: boolean }) {
  const { t } = useTranslation("connect");
  const canManage = useCan("connect.manage");
  const qc = useQueryClient();
  const key = ["connect", "overlap", companyId];
  const overlap = useQuery({ queryKey: key, queryFn: () => unwrap(api.GET("/api/v1/connect/overlap", { params: { query: { company_id: companyId } } })), staleTime: 60_000 });
  const changed = () => { void qc.invalidateQueries({ queryKey: ["connect"] }); void qc.invalidateQueries({ queryKey: ["intel"] }); void qc.invalidateQueries({ queryKey: ["command"] }); };
  const pause = useMutation({
    meta: { silent: true },
    mutationFn: (id: string) => unwrap(api.POST("/api/v1/connect/connections/{connection_id}/pause", { params: { path: { connection_id: id } } })),
    onSuccess: () => { toast(t("overlap.paused"), "ok"); changed(); },
    onError: (e) => toast(e.message, "bad"),
  });
  const choose = useMutation({
    meta: { silent: true },
    mutationFn: (v: { id: string; choice: "keep_both" | null }) => unwrap(api.POST("/api/v1/connect/connections/{connection_id}/overlap-choice", { params: { path: { connection_id: v.id } }, body: { choice: v.choice } })),
    onSuccess: (_, v) => { toast(v.choice ? t("overlap.keptToast") : t("overlap.askedToast"), "ok"); changed(); },
    onError: (e) => toast(e.message, "bad"),
  });
  // A banner must never get in the way of the page it sits on: if it cannot be read it says nothing.
  if (!overlap.data) return null;
  const o = overlap.data;
  const kept = o.connections.filter((c) => c.kept_both);
  const waiting = o.connections.filter((c) => !c.kept_both && c.status !== "paused");
  const areas = o.areas.map((a) => t(`overlap.area.${a.area}`)).join(", ");
  if (!o.overlapping) {
    if (compact || kept.length === 0) return null;
    return (
      <p className="mb-4 text-xs text-muted">
        {t("overlap.kept", { names: kept.map((c) => c.name).join(", ") })}{" "}
        {canManage && kept.map((c) => <button key={c.id} type="button" className="underline" disabled={choose.isPending} onClick={() => choose.mutate({ id: c.id, choice: null })}>{t("overlap.askAgain")}</button>)}
      </p>
    );
  }
  return (
    <Alert tone="warn" className="mb-4">
      <p className="font-medium">{t("overlap.title")}</p>
      <p className="mt-1">{t("overlap.body", { areas, names: waiting.map((c) => c.name).join(", ") })}</p>
      {canManage && (
        <ul className="mt-2 space-y-2">
          {waiting.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-2">
              {waiting.length > 1 && <span className="text-sm font-medium">{c.name}</span>}
              <Button size="sm" loading={pause.isPending && pause.variables === c.id} onClick={() => pause.mutate(c.id)}>{t("overlap.pause")}</Button>
              <Button size="sm" variant="secondary" loading={choose.isPending && choose.variables?.id === c.id} onClick={() => choose.mutate({ id: c.id, choice: "keep_both" })}>{t("overlap.keep")}</Button>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs opacity-80">{t("overlap.explain")}</p>
    </Alert>
  );
}
