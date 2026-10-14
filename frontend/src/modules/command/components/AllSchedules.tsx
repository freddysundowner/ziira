import { api, Badge, DataTable, unwrap, useQuery, useTranslation } from "@/sdk";

import { toTimeInput } from "../logic";

/** Everyone's brief schedules, for people who manage them. */
export default function AllSchedules() {
  const { t } = useTranslation("command");
  const q = useQuery({ queryKey: ["command", "schedules", "all"], queryFn: () => unwrap(api.GET("/api/v1/command/schedules")) });
  return (
    <DataTable
      rows={q.data} loading={q.isLoading} error={q.error?.message} onRetry={() => void q.refetch()} rowKey={(s) => s.id}
      searchText={(s) => s.user_name ?? ""} searchPlaceholder={t("searchPeople")}
      empty={{ title: t("noSchedules"), hint: t("noSchedulesHint") }}
      columns={[
        { header: t("person"), sortValue: (s) => s.user_name, cell: (s) => <span className="font-medium">{s.user_name ?? "—"}</span> },
        { header: t("which"), cell: (s) => t(`kind.${s.kind}`) },
        { header: t("sendTime"), cell: (s) => `${s.kind === "weekly" && s.weekday ? `${t(`weekdays.${s.weekday}`)} ` : ""}${toTimeInput(s.send_time)}` },
        { header: t("channel"), hideBelow: "sm", cell: (s) => t(`channels.${s.channel}`) },
        { header: t("status"), hideBelow: "sm", cell: (s) => <Badge tone={s.is_active ? "ok" : "neutral"}>{s.is_active ? t("active") : t("paused")}</Badge> },
      ]}
    />
  );
}
