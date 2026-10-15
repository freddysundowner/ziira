import { Alert, api, Button, DataTable, ErrorState, Select, toast, unwrap, useCan, useCompany, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

/** Which Ziira branch each store or till of the other system is. Unmapped ones stay at company level. */
export function BranchMapping({ connectionId, companyId }: { connectionId: string; companyId: string }) {
  const { t } = useTranslation("connect");
  const canManage = useCan("connect.manage");
  const queryClient = useQueryClient();
  const { companies } = useCompany(companyId);
  const branches = companies.find((c) => c.id === companyId)?.branches ?? [];
  const key = ["connect", "branches", connectionId];
  const list = useQuery({ queryKey: key, queryFn: () => unwrap(api.GET("/api/v1/connect/connections/{connection_id}/branches", { params: { path: { connection_id: connectionId } } })) });
  const save = useMutation({
    meta: { silent: true },
    mutationFn: (change: { external_ref: string; branch_id?: string | null; ignored?: boolean; create_branch?: boolean }) =>
      unwrap(api.PUT("/api/v1/connect/connections/{connection_id}/branches", { params: { path: { connection_id: connectionId } }, body: { branch_id: null, ignored: false, create_branch: false, ...change } })),
    onSuccess: (data) => { queryClient.setQueryData(key, data); void queryClient.invalidateQueries({ queryKey: ["connect", "connection", connectionId] }); toast(t("branches.saved"), "ok"); },
    onError: (e) => toast(e.message, "bad"),
  });
  if (list.error) return <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />;
  const unmapped = (list.data ?? []).filter((b) => !b.branch_id && !b.ignored).length;
  const choice = (b: { branch_id: string | null; ignored: boolean }) => (b.ignored ? "__ignore" : (b.branch_id ?? ""));
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">{t("branches.hint")}</p>
      {unmapped > 0 && <Alert tone="warn">{t("branches.unmapped", { count: unmapped })}</Alert>}
      <DataTable
        rows={list.data} loading={list.isLoading} rowKey={(b) => b.external_ref}
        empty={{ title: t("branches.empty"), hint: t("branches.emptyHint") }}
        columns={[
          { header: t("branches.theirs"), cell: (b) => <span className="font-medium">{b.external_name ?? b.external_ref}</span> },
          {
            header: t("branches.ours"),
            cell: (b) => (
              <Select aria-label={t("branches.ours")} disabled={!canManage || save.isPending} value={choice(b)}
                onChange={(e) => {
                  const v = e.target.value;
                  if (v === "__create") save.mutate({ external_ref: b.external_ref, create_branch: true });
                  else if (v === "__ignore") save.mutate({ external_ref: b.external_ref, ignored: true });
                  else save.mutate({ external_ref: b.external_ref, branch_id: v || null });
                }}>
                <option value="">{t("branches.companyLevel")}</option>
                {branches.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                <option value="__ignore">{t("branches.ignore")}</option>
                <option value="__create">{t("branches.create")}</option>
              </Select>
            ),
          },
        ]}
      />
      {save.isPending && <Button variant="secondary" loading disabled>{t("saving")}</Button>}
    </div>
  );
}
