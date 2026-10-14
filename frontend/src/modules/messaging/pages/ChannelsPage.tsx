import { useState } from "react";

import { api, EmptyState, ErrorState, Field, PageHeader, Select, SkeletonRows, unwrap, useCompany, useQuery, useTranslation } from "@/sdk";

import ChannelCard from "../components/ChannelCard";
import RecentMessages from "../components/RecentMessages";

/** Email and SMS: which gateway the business sends through, a test-send, and the latest messages. */
export default function ChannelsPage() {
  const { t } = useTranslation("messaging");
  const { company, companies } = useCompany();
  const [chosen, setChosen] = useState<string>();
  const companyId = chosen ?? company?.id;
  const channels = useQuery({
    enabled: !!companyId, queryKey: ["notification-channels", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/notifications/channels", { params: { query: { company_id: companyId! } } })),
  });
  return (
    <>
      <PageHeader title={t("title")} description={t("hint")} />
      {companies.length > 1 && (
        <Field label={t("company")} className="mb-4 max-w-xs">
          <Select value={companyId ?? ""} onChange={(e) => setChosen(e.target.value)}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
        </Field>
      )}
      {!companyId ? <EmptyState title={t("noCompany")} /> : channels.error ? <ErrorState message={channels.error.message} onRetry={() => void channels.refetch()} /> : !channels.data ? <SkeletonRows rows={3} cols={3} /> : (
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            {(["sms", "email"] as const).map((c) => (
              <ChannelCard key={c} channel={c} companyId={companyId} current={channels.data.find((x) => x.channel === c && x.status === "active")} />
            ))}
          </div>
          <RecentMessages companyId={companyId} />
        </div>
      )}
    </>
  );
}
