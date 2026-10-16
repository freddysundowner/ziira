import { Link } from "react-router-dom";

import { api, Card, channelOptions, unwrap, useChannels, useQuery, useSession, useTranslation } from "@/sdk";

/** "Your daily summary arrives at 7:00 by email": when and how, with a link to change it. */
export default function SummaryStrip() {
  const { t } = useTranslation("intel");
  const { enabledUnits, can } = useSession();
  const on = enabledUnits.has("command") && can("command.view");
  const mine = useQuery({ enabled: on, queryKey: ["command", "schedules", "mine"], queryFn: () => unwrap(api.GET("/api/v1/command/schedules/mine")) });
  const channels = useChannels().data ?? [];
  if (!on) return null;
  const daily = mine.data?.find((s) => s.kind === "daily" && s.is_active);
  const way = daily ? channelOptions(channels, daily.channel, ["in_app"]).find((o) => o.value === daily.channel) : undefined;
  return (
    <Card title={t("summary.title")}>
      {mine.error ? <p className="text-sm text-bad">{mine.error.message}</p> : !mine.data ? <p className="text-sm text-muted">{t("loading")}</p> : (
        <p className="text-sm">
          {daily
            ? t("summary.arrives", { time: daily.send_time.slice(0, 5), way: daily.channel === "in_app" ? t("summary.inApp") : (way?.label ?? daily.channel) })
            : t("summary.none")}{" "}
          <Link to="/intelligence/summary" className="font-medium text-brand-strong hover:underline">{daily ? t("summary.change") : t("summary.turnOn")}</Link>
        </p>
      )}
    </Card>
  );
}
