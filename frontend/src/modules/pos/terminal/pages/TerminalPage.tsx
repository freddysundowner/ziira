import { useMemo, useState } from "react";

import { api, EmptyState, ErrorState, SkeletonRows, unwrap, useCompany, useQuery, useSession, useTranslation } from "@/sdk";

import { branchesOf } from "../branches";
import { Centered, Frame } from "../components/Frame";
import { OpenTill } from "../components/OpenTill";
import { Selling } from "../components/Selling";
import { readText, writeText } from "../storage";

const BRANCH_KEY = "ziira.pos.branch";

/** The selling screen: finds this cashier's open till (or helps open one) and then shows the terminal. */
export default function TerminalPage() {
  const { t } = useTranslation("pos");
  const { me } = useSession();
  const { companies, isLoading } = useCompany();
  const branches = useMemo(() => branchesOf(companies), [companies]);
  const [chosen, setChosen] = useState(() => readText(BRANCH_KEY));
  const branch = branches.find((b) => b.id === chosen) ?? branches[0];

  const tills = useQuery({
    enabled: !!branch,
    queryKey: ["pos-terminal", "tills", branch?.id],
    queryFn: () => unwrap(api.GET("/api/v1/pos/tills", { params: { query: { branch_id: branch!.id, status: "open" } } })),
  });
  const devices = useQuery({
    enabled: !!branch,
    queryKey: ["pos-terminal", "devices", branch?.id],
    queryFn: () => unwrap(api.GET("/api/v1/pos/devices", { params: { query: { branch_id: branch!.id } } })),
  });

  const pick = (id: string) => { setChosen(id); writeText(BRANCH_KEY, id); };
  const till = tills.data?.find((x) => x.cashier_id === me?.user_id);
  const failed = tills.error ?? devices.error;

  if (isLoading || (branch && (tills.isLoading || devices.isLoading))) {
    return <Frame><Centered><div className="w-full max-w-md"><SkeletonRows rows={4} cols={1} /></div></Centered></Frame>;
  }
  if (!branch) return <Frame><Centered><EmptyState title={t("terminal.noBranch")} hint={t("terminal.noBranchHint")} /></Centered></Frame>;
  if (failed) {
    return <Frame><Centered><ErrorState message={failed.message} title={t("terminal.loadFailed")} onRetry={() => { void tills.refetch(); void devices.refetch(); }} /></Centered></Frame>;
  }
  if (!till) return <Frame info={branch.name}><OpenTill branches={branches} branch={branch} onBranch={pick} devices={devices.data ?? []} /></Frame>;
  return <Selling key={till.id} till={till} device={devices.data?.find((d) => d.id === till.device_id)} branch={branch} />;
}
