import { humanise } from "@/sdk";

type Translate = (key: string, options?: Record<string, unknown>) => string;

/** What the server said about an accepted sale ("price_changed:CEM:116:120"), in words. */
export function describeWarning(warning: string, t: Translate): string {
  const [code = "", ...detail] = warning.split(":");
  return t(`terminal.sync.warning.${code}`, { defaultValue: humanise(warning.replace(/:/g, " ")), detail: detail.join(" ") });
}
