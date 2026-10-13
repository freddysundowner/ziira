import { Card, PageHeader, Slot, useTranslation } from "@/sdk";

/** The home page. Modules add boxes to it through the "dashboard.widgets" slot. */
export function Home() {
  const { t } = useTranslation();
  return (
    <>
      <PageHeader title={t("home.title")} />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <Slot
          name="dashboard.widgets"
          render={(c, content) => <Card title={c.label ? t(c.label) : undefined}>{content}</Card>}
          empty={<p className="text-sm text-slate-500">{t("home.noWidgets")}</p>}
        />
      </div>
    </>
  );
}
