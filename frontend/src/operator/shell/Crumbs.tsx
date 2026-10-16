import { useLocation } from "react-router-dom";

import { Breadcrumbs, useTranslation } from "@/sdk";

import { crumbParts, NAV_GROUPS } from "../nav";

/** Where the open screen sits: group, screen and (on a detail page) the record. Nothing on the dashboard or an unknown address. */
export function Crumbs() {
  const { t } = useTranslation("operator");
  const { pathname, search } = useLocation();
  const parts = crumbParts(NAV_GROUPS, pathname, search);
  if (pathname === "/operator/account") return <Breadcrumbs items={[{ label: t("shell.account.profile") }]} />;
  if (pathname === "/operator/setup") return <Breadcrumbs items={[{ label: t("nav.groups.overview"), to: "/operator/dashboard" }, { label: t("nav.i.setup") }]} />;
  if (!parts.groupKey || !parts.itemId || parts.itemId === "dashboard") return null;
  const items: { label: string; to?: string }[] = [{ label: t(parts.groupKey) }];
  if (parts.rest && parts.itemTo) items.push({ label: t(`nav.i.${parts.itemId}`), to: parts.itemTo }, { label: parts.rest });
  else items.push({ label: t(`nav.i.${parts.itemId}`) });
  return <Breadcrumbs items={items} />;
}
