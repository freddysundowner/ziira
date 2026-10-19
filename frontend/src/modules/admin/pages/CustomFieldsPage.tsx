import { ArrowDown, ArrowUp, Eye, EyeOff, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, IconButton, PageHeader, Skeleton, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import FieldDrawer from "./fields/FieldDrawer";
import { type EntityRow, type FieldRow, groupByEntity, moved } from "./fields/lib";

/** Settings > Custom fields: the extra details a business keeps about its records (a vehicle plate, a hair type), per kind of record. */
export default function CustomFieldsPage() {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [drawer, setDrawer] = useState<{ entity: EntityRow; field: FieldRow | null } | null>(null);
  const [deleting, setDeleting] = useState<FieldRow | null>(null);
  const entities = useQuery({ queryKey: ["custom-fields", "entities"], queryFn: () => unwrap(api.GET("/api/v1/custom-fields/entities")) });
  const fields = useQuery({ queryKey: ["custom-fields", "all"], queryFn: () => unwrap(api.GET("/api/v1/custom-fields", { params: { query: { include_inactive: true } } })) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["custom-fields"] });

  const toggle = useMutation({
    mutationFn: (f: FieldRow) => unwrap(api.PATCH("/api/v1/custom-fields/{field_id}", { params: { path: { field_id: f.id } }, body: { active: !f.active } })),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (f: FieldRow) => unwrap(api.DELETE("/api/v1/custom-fields/{field_id}", { params: { path: { field_id: f.id } } })),
    onSuccess: () => { void refresh(); toast(t("fields.deleted"), "ok"); setDeleting(null); },
  });
  const reorder = useMutation({
    mutationFn: (v: { entity: string; ids: string[] }) => unwrap(api.PUT("/api/v1/custom-fields/order", { body: { entity_type: v.entity, ids: v.ids } })),
    onSuccess: refresh,
  });

  const loading = entities.isLoading || fields.isLoading;
  const error = entities.error ?? fields.error;
  const groups = groupByEntity(entities.data ?? [], fields.data ?? []);

  return (
    <>
      <PageHeader title={t("fields.title")} description={t("fields.hint")} />
      {loading && <div className="space-y-4" role="status" aria-label="Loading">{[0, 1].map((i) => <Skeleton key={i} className="h-32 rounded-xl" />)}</div>}
      {error && <ErrorState title={t("fields.loadFailed")} message={error.message} onRetry={() => { void entities.refetch(); void fields.refetch(); }} />}
      {!loading && !error && groups.length === 0 && <EmptyState title={t("fields.noRecords")} hint={t("fields.noRecordsHint")} />}
      <div className="space-y-4">
        {!loading && !error && groups.map(({ entity, fields: list }) => (
          <Card key={entity.entity_type} title={entity.label}
            actions={<Button size="sm" variant="secondary" onClick={() => setDrawer({ entity, field: null })}><Plus className="h-4 w-4" />{t("fields.add")}</Button>}>
            {list.length === 0 ? (
              <p className="text-sm text-muted">{t("fields.none", { record: entity.label.toLowerCase() })}</p>
            ) : (
              <ul className="divide-y divide-line">
                {list.map((f, n) => (
                  <li key={f.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
                    <div className="min-w-0 flex-1">
                      <p className={`truncate font-medium ${f.active ? "" : "text-muted line-through"}`}>{f.label}</p>
                      <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
                        <span>{t(`fields.kinds.${f.kind}`)}</span>
                        {f.required && <Badge>{t("fields.requiredBadge")}</Badge>}
                        {f.searchable && <Badge>{t("fields.searchableBadge")}</Badge>}
                        {f.from_pack && <Badge tone="info">{t("fields.fromPack")}</Badge>}
                        {!f.active && <Badge tone="warn">{t("fields.hidden")}</Badge>}
                      </p>
                    </div>
                    <div className="flex items-center gap-0.5">
                      <IconButton label={t("fields.moveUp", { name: f.label })} disabled={n === 0 || reorder.isPending}
                        onClick={() => reorder.mutate({ entity: entity.entity_type, ids: moved(list.map((x) => x.id), f.id, -1) })}><ArrowUp className="h-4 w-4" /></IconButton>
                      <IconButton label={t("fields.moveDown", { name: f.label })} disabled={n === list.length - 1 || reorder.isPending}
                        onClick={() => reorder.mutate({ entity: entity.entity_type, ids: moved(list.map((x) => x.id), f.id, 1) })}><ArrowDown className="h-4 w-4" /></IconButton>
                      <IconButton label={t("fields.edit", { name: f.label })} onClick={() => setDrawer({ entity, field: f })}><Pencil className="h-4 w-4" /></IconButton>
                      <IconButton label={t(f.active ? "fields.hide" : "fields.show", { name: f.label })} disabled={toggle.isPending} onClick={() => toggle.mutate(f)}>
                        {f.active ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </IconButton>
                      {!f.from_pack && <IconButton label={t("fields.delete", { name: f.label })} className="text-bad" onClick={() => setDeleting(f)}><Trash2 className="h-4 w-4" /></IconButton>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        ))}
      </div>
      <FieldDrawer open={drawer !== null} entity={drawer?.entity ?? null} field={drawer?.field ?? null} onClose={() => setDrawer(null)} />
      <ConfirmDialog open={!!deleting} onClose={() => setDeleting(null)} danger busy={remove.isPending} title={t("fields.deleteTitle")} confirmLabel={t("fields.deleteConfirm")}
        message={t("fields.deleteAsk", { name: deleting?.label })} onConfirm={() => deleting && remove.mutate(deleting)} />
    </>
  );
}
