import { Clock } from "lucide-react";

import { api, Menu, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { SNOOZE_CHOICES } from "../plainWords";
import { refreshFindings } from "../refresh";

/** "Remind me later": put a thing aside for 3 days or a week. It comes back sooner if it gets worse. */
export default function SnoozeMenu({ findingId }: { findingId: string }) {
  const { t } = useTranslation("intel");
  const qc = useQueryClient();
  const snooze = useMutation({
    mutationFn: (days: number) => unwrap(api.POST("/api/v1/intel/findings/{finding_id}/snooze", { params: { path: { finding_id: findingId } }, body: { days } })),
    onSuccess: () => { refreshFindings(qc, findingId); toast(t("snooze.done"), "ok"); },
  });
  return (
    <Menu label={t("snooze.label")} trigger={<span className="inline-flex items-center gap-1.5"><Clock className="h-4 w-4" aria-hidden />{t("snooze.label")}</span>}
      items={SNOOZE_CHOICES.map((c) => ({ label: t(`snooze.${c.id}`), onSelect: () => snooze.mutate(c.days) }))} />
  );
}
