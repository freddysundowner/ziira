import { useCompany } from "@/sdk";

import { OverlapBanner } from "../components/OverlapBanner";

/** Banner above the Command Center panels and the findings list. Receives { companyId } (else the active company). */
export default function OverlapSlot({ companyId }: { companyId?: string }) {
  const { company } = useCompany();
  const id = companyId || company?.id;
  return id ? <OverlapBanner companyId={id} compact /> : null;
}
