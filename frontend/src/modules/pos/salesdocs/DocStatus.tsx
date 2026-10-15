import { Badge, humanise, useTranslation } from "@/sdk";

import { statusTone } from "./lib";

/** A document status code as a coloured, translated badge. */
export function DocStatus({ status }: { status: string }) {
  const { t } = useTranslation("pos");
  return <Badge tone={statusTone(status)}>{t(`docs.status.${status}`, humanise(status))}</Badge>;
}
