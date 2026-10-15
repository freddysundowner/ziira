import { useRef, useState } from "react";

import { api, Alert, Button, Card, Field, NumberInput, Select, unwrap, useMutation, useQueryClient, useTranslation, type Schemas } from "@/sdk";

import type { BranchInfo } from "../branches";
import { readText, writeText } from "../storage";
import { Centered } from "./Frame";

const DEVICE_KEY = "ziira.pos.device";

/** No till is open for this cashier: pick the till (device) and say how much cash is in the drawer. */
export function OpenTill({ branches, branch, onBranch, devices, offline }: {
  branches: BranchInfo[]; branch: BranchInfo; onBranch: (id: string) => void; devices: Schemas["DeviceOut"][]; offline: boolean;
}) {
  const { t } = useTranslation("pos");
  const qc = useQueryClient();
  const active = devices.filter((d) => d.status === "active");
  const remembered = readText(`${DEVICE_KEY}.${branch.id}`);
  const [deviceId, setDeviceId] = useState(active.some((d) => d.id === remembered) ? remembered : (active[0]?.id ?? ""));
  const [float, setFloat] = useState("0");
  // One id per opening form, so a retry after a dropped connection opens the till once.
  const localId = useRef(crypto.randomUUID());

  const open = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/pos/tills", { body: { device_id: deviceId, opening_float: float || "0", local_id: localId.current } })),
    onSuccess: () => {
      writeText(`${DEVICE_KEY}.${branch.id}`, deviceId);
      void qc.invalidateQueries({ queryKey: ["pos-terminal", "branch"] });
    },
  });

  return (
    <Centered>
      <Card title={t("terminal.open.title")} description={t("terminal.open.hint")} className="w-full max-w-md">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (deviceId && !offline) open.mutate(); }}>
          {branches.length > 1 && (
            <Field label={t("terminal.open.branch")}>
              <Select value={branch.id} onChange={(e) => onBranch(e.target.value)}>
                {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </Select>
            </Field>
          )}
          {active.length === 0 ? (
            <Alert tone="warn">{t("terminal.open.noDevice")}</Alert>
          ) : (
            <Field label={t("terminal.open.device")}>
              <Select value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
                {active.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.code})</option>)}
              </Select>
            </Field>
          )}
          <Field label={t("terminal.open.float")} hint={t("terminal.open.floatHint")}>
            <NumberInput value={float} onChange={setFloat} data-autofocus autoFocus />
          </Field>
          {offline && <Alert tone="warn">{t("terminal.sync.openNeedsConnection")}</Alert>}
          {open.error && <Alert tone="bad">{open.error.message}</Alert>}
          <Button type="submit" size="lg" className="w-full" loading={open.isPending} disabled={!deviceId || offline}>{open.error ? t("terminal.retry") : t("terminal.open.submit")}</Button>
        </form>
      </Card>
    </Centered>
  );
}
