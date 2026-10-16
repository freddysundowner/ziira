import { Check, Circle, Loader2, X } from "lucide-react";

import { cx, useTranslation } from "@/sdk";

import { type PasswordRules, passwordStrength } from "./validators";

export type ServerCheck = "idle" | "checking" | "ok" | "refused" | "unreachable";

const BAR = ["bg-line", "bg-bad", "bg-warn", "bg-info", "bg-ok"];

function Rule({ state, children }: { state: "ok" | "bad" | "pending" | "idle"; children: string }) {
  const Icon = state === "ok" ? Check : state === "bad" ? X : state === "pending" ? Loader2 : Circle;
  return (
    <li className={cx("flex items-center gap-2 text-sm", state === "ok" ? "text-ok" : state === "bad" ? "text-bad" : "text-muted")}>
      <Icon className={cx("h-4 w-4 shrink-0", state === "pending" && "animate-spin")} aria-hidden />
      <span>{children}</span>
    </li>
  );
}

/** A strength bar and a live checklist. "Too common" comes from the server's own check; its plain message is shown when it refuses. */
export function PasswordMeter({ password, rules, server, serverMessage, matches }: {
  password: string; rules: PasswordRules; server: ServerCheck; serverMessage: string | null; matches: boolean | null;
}) {
  const { t } = useTranslation();
  const strength = passwordStrength(password);
  const tone = (ok: boolean): "ok" | "idle" | "bad" => (!password ? "idle" : ok ? "ok" : "bad");
  return (
    <div className="space-y-3" data-testid="password-meter">
      <div>
        <div className="flex gap-1.5" aria-hidden>
          {[1, 2, 3, 4].map((i) => <span key={i} className={cx("h-1.5 flex-1 rounded-full transition-colors", i <= strength ? BAR[strength] : "bg-line")} />)}
        </div>
        <p className="mt-1.5 text-xs text-muted" aria-live="polite">{t("signup.strength.label")}: {t(`signup.strength.${strength}`)}</p>
      </div>
      <ul className="space-y-1.5">
        <Rule state={tone(rules.length)}>{t("signup.rules.length")}</Rule>
        <Rule state={!password ? "idle" : rules.long ? "ok" : "idle"}>{t("signup.rules.long")}</Rule>
        <Rule state={tone(rules.notEmail)}>{t("signup.rules.notEmail")}</Rule>
        <Rule state={server === "refused" ? "bad" : server === "ok" ? "ok" : server === "checking" ? "pending" : "idle"}>{t("signup.rules.common")}</Rule>
        {matches !== null && <Rule state={matches ? "ok" : "bad"}>{t("signup.rules.match")}</Rule>}
      </ul>
      {server === "refused" && serverMessage && <p role="alert" className="text-sm text-bad">{serverMessage}</p>}
    </div>
  );
}
