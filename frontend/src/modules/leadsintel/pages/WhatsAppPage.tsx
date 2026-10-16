import { useState } from "react";

import { EmptyState, Field, PageHeader, Select, Tabs, useCompany, useTranslation } from "@/sdk";

import ConnectionTab from "../components/ConnectionTab";
import InboxTab from "../components/InboxTab";
import TemplatesTab from "../components/TemplatesTab";

type Tab = "connection" | "templates" | "inbox";

/** Connect the business's WhatsApp number through Lead Intel, see which message templates are approved, read replies. */
export default function WhatsAppPage() {
  const { t } = useTranslation("leadsintel");
  const { company, companies } = useCompany();
  const [chosen, setChosen] = useState<string>();
  const [tab, setTab] = useState<Tab>("connection");
  const companyId = chosen ?? company?.id;
  return (
    <>
      <PageHeader title={t("menu")} description={t("hint")} />
      {companies.length > 1 && (
        <Field label={t("company")} className="mb-4 max-w-xs">
          <Select value={companyId ?? ""} onChange={(e) => setChosen(e.target.value)}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
        </Field>
      )}
      {!companyId ? <EmptyState title={t("noCompany")} /> : (
        <>
          <Tabs value={tab} onChange={setTab} tabs={[{ id: "connection", label: t("tabConnection") }, { id: "templates", label: t("tabTemplates") }, { id: "inbox", label: t("tabInbox") }]} />
          <div className="mt-4">
            {tab === "connection" && <ConnectionTab companyId={companyId} />}
            {tab === "templates" && <TemplatesTab companyId={companyId} />}
            {tab === "inbox" && <InboxTab companyId={companyId} />}
          </div>
        </>
      )}
    </>
  );
}
