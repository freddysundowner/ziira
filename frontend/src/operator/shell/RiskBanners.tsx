import { ShieldAlert, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Alert, IconButton, useTranslation } from "@/sdk";

import { useOperatorMe } from "../me";
import { useSetup } from "./data";

const PREFIX = "ziira.operator.risk.";

/** A banner is hidden for this browser session once closed; it comes back the next time while the risk is still there. */
function closed(key: string): boolean {
  try {
    return sessionStorage.getItem(PREFIX + key) === "1";
  } catch {
    return false;
  }
}

/**
 * Risky settings that are on, under the top bar: no second factor in production, registration open without working mail,
 * mail not configured, no AI provider. Each says what is wrong and links to where it is fixed.
 */
export function RiskBanners() {
  const { t } = useTranslation("operator");
  const me = useOperatorMe();
  const setup = useSetup();
  const [, bump] = useState(0);
  const risks = [
    ...(me.data?.mfa_off_in_production ? [{ key: "mfa_off", severity: "bad" as const, to: "/operator/account" }] : []),
    ...(setup.data?.risks.filter((r) => r.key !== "mfa_off") ?? []),
  ].filter((r) => !closed(r.key));
  if (risks.length === 0) return null;
  const close = (key: string) => {
    try {
      sessionStorage.setItem(PREFIX + key, "1");
    } catch {
      // closed until the page is reloaded
    }
    bump((n) => n + 1);
  };
  return (
    <div className="space-y-2 px-4 pt-3 sm:px-6" role="region" aria-label={t("shell.risks.label")}>
      {risks.map((r) => (
        <Alert key={r.key} tone={r.severity === "bad" ? "bad" : r.severity === "warn" ? "warn" : "info"}>
          <div className="flex items-start gap-3">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="font-medium">{t(`shell.risks.${r.key}.title`)}</p>
              <p className="text-sm">{t(`shell.risks.${r.key}.text`)} <Link to={r.to} className="font-medium underline">{t(`shell.risks.${r.key}.fix`)}</Link></p>
            </div>
            <IconButton label={t("shell.risks.dismiss")} className="-my-1 h-7 w-7" onClick={() => close(r.key)}><X className="h-4 w-4" /></IconButton>
          </div>
        </Alert>
      ))}
    </div>
  );
}
