import { useState } from "react";

import { Field, PageHeader, Select, useCan, useCompany, useTranslation } from "@/sdk";

import Glossary from "../components/Glossary";
import ActionsSettings from "../settings/ActionsSettings";

/** How much Ziira does for you: Watch, Ask, Prepare or Act for me; the things it may do by itself; and what it did. */
export default function HowMuchPage() {
  const { t } = useTranslation("intel");
  const { companies, company } = useCompany();
  const [picked, setPicked] = useState("");
  const canView = useCan("findings.view");
  const companyId = picked || company?.id;
  return (
    <>
      <PageHeader title={t("how.page")} description={t("how.pageHint")} actions={<Glossary terms={["watch", "ask", "prepare", "act"]} />} />
      {companies.length > 1 && (
        <div className="mb-4 max-w-xs"><Field label={t("company")}>
          <Select value={companyId ?? ""} onChange={(e) => setPicked(e.target.value)}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
        </Field></div>
      )}
      {canView && <ActionsSettings companyId={companyId} />}
    </>
  );
}
