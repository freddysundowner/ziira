import { Link } from "react-router-dom";

import { api, Card, unwrap, useQuery, useTranslation } from "@/sdk";

import { SeverityBadge } from "../components/Badges";
import { usePlain } from "../usePlain";

/** Other things about the same person or place, so a pattern is easy to see. Hidden when there are none. */
export default function RelatedCard({ findingId }: { findingId: string }) {
  const { t } = useTranslation("intel");
  const plain = usePlain();
  const q = useQuery({ queryKey: ["intel", "related", findingId], queryFn: () => unwrap(api.GET("/api/v1/intel/findings/{finding_id}/related", { params: { path: { finding_id: findingId } } })) });
  if (!q.data || q.data.length === 0) return null;
  return (
    <Card title={t("related.title")} description={t("related.hint")}>
      <ul className="divide-y divide-line">
        {q.data.map((r) => (
          <li key={r.id} className="flex items-start gap-2 py-2 text-sm first:pt-0 last:pb-0">
            <SeverityBadge severity={r.severity} />
            <Link to={`/intelligence/things/${r.id}`} className="min-w-0 flex-1 hover:underline">{plain.check(r.check_code)?.title ?? r.summary}</Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}
