import { Plus } from "lucide-react";
import { Link } from "react-router-dom";

import { Button, PageHeader, useCan, useTranslation } from "@/sdk";

import { OrdersList } from "../components/OrdersList";

export default function OrdersPage() {
  const { t } = useTranslation("purchasing");
  const canOrder = useCan("po.create");
  return (
    <>
      <PageHeader title={t("orders")} description={t("ordersHint")}
        actions={canOrder && <Link to="/orders/new"><Button><Plus className="h-4 w-4" />{t("newOrder")}</Button></Link>} />
      <OrdersList />
    </>
  );
}
