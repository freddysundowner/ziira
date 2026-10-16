import { Check } from "lucide-react";
import { Link } from "react-router-dom";

import { api, Card, unwrap, useCan, useQuery, useSession, useTranslation } from "@/sdk";

const SOURCES: [unit: string, key: string][] = [
  ["pos", "sales"], ["inventory", "stock"], ["payments", "payments"], ["purchasing", "suppliers"], ["finance", "books"], ["people", "staff"], ["crm", "customers"], ["connect", "other"],
];

/** "What Ziira can see": the parts of the business it reads, and how many things it watches in them. */
export default function SeeStrip() {
  const { t } = useTranslation("intel");
  const { enabledUnits } = useSession();
  const canManage = useCan("findings.manage");
  const topics = useQuery({ queryKey: ["intel", "topics"], queryFn: () => unwrap(api.GET("/api/v1/intel/topics")) });
  const watched = (topics.data?.topics ?? []).reduce((n, x) => n + x.enabled, 0);
  const seen = SOURCES.filter(([unit]) => enabledUnits.has(unit));
  return (
    <Card title={t("see.title")}>
      <ul className="flex flex-wrap gap-1.5">
        {seen.map(([unit, key]) => (
          <li key={unit} className="inline-flex items-center gap-1 rounded-full bg-sunken px-2.5 py-1 text-xs"><Check className="h-3 w-3 text-ok" aria-hidden />{t(`see.source.${key}`)}</li>
        ))}
      </ul>
      {topics.data && watched > 0 && <p className="mt-3 text-sm text-muted">{t("see.watching", { count: watched })}{" "}
        {canManage && <Link to="/intelligence/watching" className="font-medium text-brand-strong hover:underline">{t("see.change")}</Link>}</p>}
    </Card>
  );
}
