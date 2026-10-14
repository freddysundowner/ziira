import { Link } from "react-router-dom";

import { Button, EmptyState, useTranslation } from "@/sdk";

export function NotFound() {
  const { t } = useTranslation();
  return <EmptyState title={t("notFound")} hint={t("notFoundHint")} action={<Link to="/"><Button>{t("home.menu")}</Button></Link>} />;
}
