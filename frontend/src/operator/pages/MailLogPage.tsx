import { useState } from "react";

import { Button, PageHeader, useTranslation } from "@/sdk";

import { MailLog } from "./email/MailLog";

/** System > Mail log: what the platform emailed lately (kind, masked recipient, result). */
export default function MailLogPage() {
  const { t } = useTranslation("operator");
  const [version, setVersion] = useState(0);
  return (
    <>
      <PageHeader title={t("mailLog.title")} description={t("mailLog.description")} actions={<Button variant="secondary" onClick={() => setVersion((v) => v + 1)}>{t("health.refresh")}</Button>} />
      <MailLog version={version} />
    </>
  );
}
