import { useState } from "react";

import { Alert, api, Button, Card, Field, FormGrid, Input, money, Select, today, unwrap, useMutation, useTranslation } from "@/sdk";

import { useStaff } from "../hooks";
import type { Project } from "../types";
import { ProjectPicker } from "./ProjectPicker";
import { ServiceItemPicker } from "./ServiceItemPicker";

/** "What rate would this get?": asks the server which row of the card prices a piece of work. */
export function RateChecker({ companyId, currency, canSeeCost }: { companyId: string; currency?: string; canSeeCost: boolean }) {
  const { t } = useTranslation("timebilling");
  const staff = useStaff(companyId);
  const [day, setDay] = useState(() => today());
  const [project, setProject] = useState<Project | null>(null);
  const [user, setUser] = useState("");
  const [service, setService] = useState("");
  const [kind, setKind] = useState<"bill" | "cost">("bill");
  const ask = useMutation({
    mutationFn: () => unwrap(api.GET("/api/v1/timebilling/rates/explain", { params: { query: {
      company_id: companyId, day, project_id: project?.id, user_id: user || undefined, service_product_id: service || undefined, kind } } })),
  });
  return (
    <Card title={t("rates.checkTitle")} description={t("rates.checkHint")}>
      <div className="space-y-4">
        <FormGrid cols={3}>
          <Field label={t("projectField")}><ProjectPicker companyId={companyId} activeOnly={false} clearable value={project?.id ?? ""} label={project ? `${project.code} · ${project.name}` : undefined} onChange={setProject} /></Field>
          <Field label={t("rates.person")}><Select value={user} onChange={(e) => setUser(e.target.value)}><option value="">{t("rates.anyone")}</option>{(staff.data ?? []).map((s) => <option key={s.user_id} value={s.user_id}>{s.name}</option>)}</Select></Field>
          <Field label={t("projects.serviceItem")}><ServiceItemPicker value={service} onChange={setService} /></Field>
          <Field label={t("date")}><Input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>
          {canSeeCost && <Field label={t("rates.kind")}><Select value={kind} onChange={(e) => setKind(e.target.value as "bill" | "cost")}><option value="bill">{t("rates.kindBill")}</option><option value="cost">{t("rates.kindCost")}</option></Select></Field>}
        </FormGrid>
        <Button variant="secondary" loading={ask.isPending} disabled={!day} onClick={() => ask.mutate()}>{t("rates.check")}</Button>
        {ask.data && (ask.data.rate
          ? <Alert tone="ok"><strong className="tnum">{t("rates.result", { rate: money(ask.data.rate.rate, currency) })}</strong> {t("rates.resultFrom", { covers: coverText(ask.data.rate, t) })}</Alert>
          : <Alert tone="warn">{t("rates.noResult")}</Alert>)}
      </div>
    </Card>
  );
}

function coverText(rate: { project_id: string | null; client_id: string | null; user_id: string | null; service_product_id: string | null; role_title: string | null }, t: (k: string) => string): string {
  const parts = [rate.project_id && t("projectField"), rate.client_id && t("client"), rate.user_id && t("rates.person"), rate.service_product_id && t("projects.serviceItem"), rate.role_title && t("rates.role")].filter(Boolean);
  return parts.length ? parts.join(", ").toLowerCase() : t("rates.everything");
}
