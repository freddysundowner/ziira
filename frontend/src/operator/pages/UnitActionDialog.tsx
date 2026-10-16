import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Button, ErrorState, Field, Input, Modal, type Schemas, Skeleton, toast, useTranslation } from "@/sdk";

import { opApi, OperatorApiError, opUnwrap } from "../client";
import { installList, type UnitAction } from "../lib";
import { useChange } from "../stepUp";

type Unit = Schemas["PlatformUnit"];

/**
 * Confirms an install, upgrade or uninstall: shows what the server says it would do (the plan), what stands in the way,
 * and asks for the unit's name before an uninstall.
 */
export function UnitActionDialog({ unit, action, onClose }: { unit: Unit; action: UnitAction; onClose: () => void }) {
  const { t } = useTranslation("operator");
  const queryClient = useQueryClient();
  const [typed, setTyped] = useState("");
  const plan = useQuery({
    queryKey: ["operator", "plan", unit.name, action],
    queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/units/{name}/plan", { params: { path: { name: unit.name }, query: { action } } })),
    staleTime: 0,
    gcTime: 0,
  });

  const run = useChange(
    async () => {
      const params = { params: { path: { name: unit.name } } };
      if (action === "install") return opUnwrap(opApi.POST("/api/v1/operator/units/{name}/install", params));
      if (action === "upgrade") return opUnwrap(opApi.POST("/api/v1/operator/units/{name}/upgrade", params));
      return opUnwrap(opApi.POST("/api/v1/operator/units/{name}/uninstall", { ...params, body: { confirm: typed } }));
    },
    {
      onSuccess: () => {
        toast(t(`units.done.${action}`, { unit: unit.title }), "ok");
        void queryClient.invalidateQueries({ queryKey: ["operator"] });
        onClose();
      },
      onError: (error) => {
        toast(error.message, "bad");
        if (error instanceof OperatorApiError) void plan.refetch();
      },
    },
  );

  const data = plan.data;
  const blocked = (data?.blocked.length ?? 0) > 0;
  const ready = !!data && !blocked && (action !== "uninstall" || typed === unit.name);

  return (
    <Modal open onClose={onClose} title={t(`units.dialog.${action}`, { unit: unit.title })} size="md"
      footer={<>
        <Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button variant={action === "uninstall" ? "danger" : "primary"} loading={run.isPending} disabled={!ready} onClick={() => run.mutate(undefined)}>
          {t(`units.actions.${action}`)}
        </Button>
      </>}>
      {plan.isPending && <div className="space-y-2"><Skeleton className="h-5 w-2/3" /><Skeleton className="h-5 w-1/2" /></div>}
      {plan.isError && <ErrorState message={plan.error.message} onRetry={() => void plan.refetch()} />}
      {data && (
        <div className="space-y-4 text-sm">
          {blocked && <Alert tone="bad"><ul className="list-disc space-y-1 pl-4">{data.blocked.map((b) => <li key={b}>{b}</li>)}</ul></Alert>}

          {action === "install" && data.will_install.length > 0 && (
            <div>
              <p>{t("units.install.willInstall", { count: data.will_install.length })}</p>
              <ul className="mt-2 divide-y divide-line rounded-lg border border-line">
                {data.will_install.map((u) => (
                  <li key={u.name} className="flex items-center justify-between px-3 py-2">
                    <span>{u.title} <span className="font-mono text-xs text-muted">{u.name}</span></span>
                    <span className="tnum text-xs text-muted">{u.version}</span>
                  </li>
                ))}
              </ul>
              {data.will_install.length > 1 && <p className="mt-2 text-xs text-muted">{t("units.install.alsoNeeds", { list: installList(data) })}</p>}
              <p className="mt-2 text-xs text-muted">{t("units.install.noData")}</p>
            </div>
          )}

          {action === "upgrade" && data.upgrades.map((u) => (
            <div key={u.name}>
              <p className="font-medium">{u.title}: <span className="tnum">{u.from_version} {"->"} {u.to_version}</span></p>
              {u.businesses.length === 0
                ? <p className="text-xs text-muted">{t("units.upgrade.noBusinesses")}</p>
                : (
                  <ul className="mt-2 divide-y divide-line rounded-lg border border-line">
                    {u.businesses.map((b) => (
                      <li key={b.code} className="px-3 py-2">
                        <span className="font-mono text-xs">{b.code}</span>
                        <span className="ml-2 text-xs text-muted">{b.migrations.join(", ")}</span>
                      </li>
                    ))}
                  </ul>
                )}
            </div>
          ))}

          {action === "uninstall" && (
            <>
              {data.holders.length > 0 && (
                <ul className="divide-y divide-line rounded-lg border border-line">
                  {data.holders.map((h) => (
                    <li key={h.code} className="flex items-center justify-between px-3 py-2">
                      <span>{h.name} <span className="font-mono text-xs text-muted">{h.code}</span></span>
                      <span className="text-xs text-muted">{t(h.enabled ? "units.uninstall.on" : "units.uninstall.dataOnly")}</span>
                    </li>
                  ))}
                </ul>
              )}
              {!blocked && (
                <>
                  <p>{t("units.uninstall.explain")}</p>
                  <Field label={t("units.uninstall.typeName", { name: unit.name })}>
                    <Input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} className="font-mono" />
                  </Field>
                </>
              )}
            </>
          )}
        </div>
      )}
    </Modal>
  );
}
