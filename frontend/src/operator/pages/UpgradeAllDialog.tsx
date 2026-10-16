import { useState } from "react";

import { Alert, Badge, Button, Modal, type Schemas, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../client";
import { useStepUp } from "../stepUp";

type Target = { code: string; name: string };
type Result = Schemas["UpgradeResult"];

/**
 * Upgrades the businesses that are behind one at a time, so the screen can show progress and what happened to each; a
 * business that fails does not stop the rest. The first call asks for a fresh code if one is needed.
 */
export function UpgradeAllDialog({ targets, onClose }: { targets: Target[]; onClose: () => void }) {
  const { t } = useTranslation("operator");
  const withStepUp = useStepUp();
  const [results, setResults] = useState<Result[]>([]);
  const [running, setRunning] = useState(false);
  const [started, setStarted] = useState(false);
  const done = results.length === targets.length;

  async function start() {
    setRunning(true);
    setStarted(true);
    for (const target of targets) {
      try {
        const [result] = await withStepUp(() => opUnwrap(opApi.POST("/api/v1/operator/businesses/upgrade", { body: { codes: [target.code] } })));
        setResults((all) => [...all, result ?? { code: target.code, name: target.name, ok: true, applied: {}, error: null }]);
      } catch (error) {
        setResults((all) => [...all, { code: target.code, name: target.name, ok: false, applied: {}, error: (error as Error).message || t("upgradeAll.stopped") }]);
        if (!((error as Error).message)) break;                 // the code box was closed: stop here
      }
    }
    setRunning(false);
  }

  const failed = results.filter((r) => !r.ok).length;
  return (
    <Modal open onClose={running ? () => undefined : onClose} title={t("upgradeAll.title")} size="md"
      footer={started
        ? <Button onClick={onClose} disabled={running}>{t("done")}</Button>
        : <><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button onClick={() => void start()}>{t("upgradeAll.start", { count: targets.length })}</Button></>}>
      <div className="space-y-3 text-sm">
        {!started && <p className="text-muted">{t("upgradeAll.explain", { count: targets.length })}</p>}
        {started && (
          <div role="progressbar" aria-valuemin={0} aria-valuemax={targets.length} aria-valuenow={results.length} aria-label={t("upgradeAll.progress")}
            className="h-2 overflow-hidden rounded-full bg-sunken">
            <div className="h-full bg-brand transition-all" style={{ width: `${(results.length / targets.length) * 100}%` }} />
          </div>
        )}
        <ul className="divide-y divide-line rounded-lg border border-line">
          {targets.map((target) => {
            const r = results.find((x) => x.code === target.code);
            return (
              <li key={target.code} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                <span>{target.name} <span className="font-mono text-xs text-muted">{target.code}</span></span>
                {!r ? <Badge tone="neutral">{running ? t("upgradeAll.waiting") : t("upgradeAll.pending")}</Badge>
                  : r.ok ? <Badge tone="ok">{t("upgradeAll.upgraded", { count: Object.values(r.applied).reduce((n, files) => n + files.length, 0) })}</Badge>
                    : <Badge tone="bad">{t("upgradeAll.failed")}</Badge>}
                {r?.error && <p className="w-full text-xs text-bad">{r.error}</p>}
              </li>
            );
          })}
        </ul>
        {done && (failed ? <Alert tone="bad">{t("upgradeAll.someFailed", { count: failed })}</Alert> : <Alert tone="ok">{t("upgradeAll.allDone")}</Alert>)}
      </div>
    </Modal>
  );
}
