import { Plus } from "lucide-react";
import { Link } from "react-router-dom";

import { Button, PageHeader, useCan, useTranslation } from "@/sdk";

import { BillsList } from "../components/BillsList";

export default function BillsPage() {
  const { t } = useTranslation("purchasing");
  const canBill = useCan("bills.manage");
  return (
    <>
      <PageHeader title={t("bills")} description={t("billsHint")}
        actions={canBill && <Link to="/bills/new"><Button><Plus className="h-4 w-4" />{t("newBill")}</Button></Link>} />
      <BillsList />
    </>
  );
}
