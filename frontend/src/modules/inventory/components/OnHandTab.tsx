import { useState } from "react";

import { api, Badge, Checkbox, DataTable, Pager, Select, quantity, unwrap, useCompany, usePagedList, useTranslation } from "@/sdk";

import { useLocations } from "../lookups";
import { LocationSelect } from "./LocationSelect";

/** Balances per location, product and batch, filtered by branch or location. */
export function OnHandTab() {
  const { t } = useTranslation("inventory");
  const { companies } = useCompany();
  const locations = useLocations();
  const branches = companies.flatMap((c) => c.branches);
  const [branchId, setBranchId] = useState("");
  const [locationId, setLocationId] = useState("");
  const [zero, setZero] = useState(false);
  const list = usePagedList(["inv-balances", branchId, locationId, zero], (limit, offset) =>
    unwrap(api.GET("/api/v1/inventory/balances", { params: { query: {
      branch_id: branchId || undefined, location_id: locationId || undefined, include_zero: zero, limit, offset } } })));
  const kind = (id: string) => locations.data?.find((l) => l.id === id)?.kind;

  return (
    <DataTable
      rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()}
      rowKey={(b) => `${b.location_id}-${b.product_id}-${b.batch_id ?? ""}`} rowHref={(b) => `/products/${b.product_id}`}
      searchText={(b) => `${b.product_name ?? ""} ${b.sku ?? ""}`} searchPlaceholder={t("searchOnPage")}
      toolbar={
        <>
          {branches.length > 1 && (
            <Select aria-label={t("branch")} className="w-44" value={branchId} onChange={(e) => { setBranchId(e.target.value); setLocationId(""); }}>
              <option value="">{t("allBranches")}</option>
              {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </Select>
          )}
          <div className="w-52"><LocationSelect label={t("location")} value={locationId} onChange={setLocationId} allLabel={t("allLocations")} /></div>
          <Checkbox label={t("showZero")} checked={zero} onChange={(e) => setZero(e.target.checked)} />
        </>
      }
      empty={{ title: t("noStock"), hint: t("noStockHint") }}
      columns={[
        { header: t("product"), sortValue: (b) => b.product_name, cell: (b) => <span><span className="font-medium">{b.product_name ?? "—"}</span> <span className="font-mono text-xs text-muted">{b.sku}</span></span> },
        { header: t("location"), hideBelow: "sm", cell: (b) => <span>{b.location_code}{kind(b.location_id) === "transit" && <Badge className="ml-2" tone="info">{t("kinds.transit")}</Badge>}</span> },
        { header: t("batch"), hideBelow: "md", cell: (b) => (b.batch_id ? <span className="font-mono text-xs">{b.batch_id.slice(0, 8)}</span> : "—") },
        { header: t("quantity"), align: "right", sortValue: (b) => Number(b.quantity), cell: (b) => <span className={Number(b.quantity) < 0 ? "font-medium text-bad" : "font-medium"}>{quantity(b.quantity)}</span> },
      ]}
      footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
    />
  );
}
