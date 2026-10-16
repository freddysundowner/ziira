import { lazy, Suspense, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";

import { Alert, ErrorState, PageHeader, Spinner, Tabs, useTranslation } from "@/sdk";

import { useAvailability, useSiteStatus } from "./website/api";

const TABS = {
  company: lazy(() => import("./website/CompanyTab")),
  social: lazy(() => import("./website/SocialTab")),
  seo: lazy(() => import("./website/SeoTab")),
  pages: lazy(() => import("./website/PagesTab")),
  media: lazy(() => import("./website/MediaTab")),
  banner: lazy(() => import("./website/BannerTab")),
  pricing: lazy(() => import("./website/PricingTab")),
  publish: lazy(() => import("./website/PublishTab")),
};
type TabId = keyof typeof TABS;
const ORDER = Object.keys(TABS) as TabId[];

/**
 * The Website area: what the marketing site says (company, contact, social, SEO, legal pages, pictures, banner) and
 * the publish step that makes it public. Tabs already opened stay mounted, so a half-filled form survives a look at
 * another tab. Hidden entirely in a self-hosted deployment, and for staff without website permission.
 */
export default function WebsitePage() {
  const { t } = useTranslation("operator");
  const availability = useAvailability();
  const status = useSiteStatus();
  const [params, setParams] = useSearchParams();
  const asked = params.get("tab");
  const tab: TabId = ORDER.includes(asked as TabId) ? (asked as TabId) : "company";
  const [opened, setOpened] = useState<Set<TabId>>(new Set([tab]));

  if (availability.isError) return <ErrorState message={availability.error.message} onRetry={() => void availability.refetch()} />;
  if (availability.data && (!availability.data.available || !availability.data.can_edit)) return <Navigate to="/operator/units" replace />;
  const pending = status.data?.pending.length ?? 0;

  function go(id: TabId) {
    setOpened((s) => new Set(s).add(id));
    setParams({ tab: id }, { replace: true });
  }

  return (
    <>
      <PageHeader title={t("website.title")} description={t("website.description")} />
      {pending > 0 && tab !== "publish" && (
        <Alert tone="warn" className="mb-4">
          {t("website.unpublished", { count: pending })} <Link to="?tab=publish" className="font-medium underline">{t("website.goPublish")}</Link>
        </Alert>
      )}
      <Tabs tabs={ORDER.map((id) => ({ id, label: t(`website.tabs.${id}`), count: id === "publish" && pending > 0 ? pending : undefined }))} value={tab} onChange={go} />
      {ORDER.filter((id) => opened.has(id) || id === tab).map((id) => {
        const Body = TABS[id];
        return (
          <div key={id} hidden={id !== tab}>
            <Suspense fallback={<div className="flex items-center gap-2 p-8 text-sm text-muted"><Spinner /> {t("loading")}</div>}><Body /></Suspense>
          </div>
        );
      })}
    </>
  );
}
