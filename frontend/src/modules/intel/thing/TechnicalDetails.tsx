import { Link } from "react-router-dom";

import { api, Badge, Card, DetailList, humanise, unwrap, useQuery, useTranslation } from "@/sdk";
import type { Schemas } from "@/sdk";

import { recordPath } from "../plainWords";

type Finding = Schemas["FindingDetailOut"];

/** The Expert layer of one thing: the check's code, the limits it used, the raw numbers and the records behind it. */
export default function TechnicalDetails({ finding: f }: { finding: Finding }) {
  const { t } = useTranslation("intel");
  const checks = useQuery({ queryKey: ["intel", "checks"], queryFn: () => unwrap(api.GET("/api/v1/intel/checks")) });
  const check = checks.data?.find((c) => c.code === f.check_code);
  const raw = (v: string | null | undefined) => v ?? "—";
  return (
    <Card title={t("tech.title")} description={t("tech.hint")}>
      <div className="space-y-4">
        <DetailList items={[
          { label: t("tech.checkCode"), value: <span className="font-mono">{f.check_code ?? "—"}</span> },
          { label: t("tech.checkName"), value: f.check_title ?? "—" },
          { label: t("tech.findingId"), value: <span className="font-mono text-xs">{f.id}</span> },
          { label: t("tech.limits"), value: check ? <span className="font-mono text-xs">{Object.entries(check.params).map(([k, v]) => `${k} = ${String(v)}`).join(", ") || "—"}</span> : "—" },
          { label: t("tech.numbers"), value: <span className="font-mono text-xs">value {raw(f.value)} · expected {raw(f.expected_value)} · amount {raw(f.amount)} · {f.severity} · {f.status}</span> },
          ...Object.entries(f.figures).map(([k, v]) => ({ label: k, value: <span className="font-mono text-xs">{v}</span> })),
        ]} />
        {f.records.length > 0 && (
          <ul className="divide-y divide-line">
            {f.records.map((r, i) => {
              const path = recordPath(r);
              return (
                <li key={`${r.type}-${r.id ?? i}`} className="flex flex-wrap items-center gap-2 py-2 text-sm first:pt-0 last:pb-0">
                  <Badge>{t(`record.${r.type.replace(/\./g, "_")}`, humanise(r.type.split(".").pop()))}</Badge>
                  {path ? <Link className="text-brand-strong hover:underline" to={path}>{r.label}</Link> : <span>{r.label}</span>}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Card>
  );
}
