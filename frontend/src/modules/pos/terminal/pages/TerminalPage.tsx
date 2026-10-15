import { useEffect, useMemo, useRef, useState } from "react";

import { api, EmptyState, ErrorState, SkeletonRows, unwrap, useCan, useQuery, useQueryClient, useSession, useTranslation } from "@/sdk";

import { branchesOf } from "../branches";
import { Centered, Frame } from "../components/Frame";
import { OpenTill } from "../components/OpenTill";
import { Selling } from "../components/Selling";
import { type CacheScope, useTerminalCache } from "../offline/cache";
import { useOnline, useOutbox } from "../offline/hooks";
import { branchKey, networkFirst, orgKey } from "../offline/snapshot";
import { readText, writeText } from "../storage";

const BRANCH_KEY = "ziira.pos.branch";

/**
 * The selling screen: finds this cashier's open till (or helps open one) and then shows the terminal. Everything it needs
 * to start is also kept on the device, so a page loaded without a connection still shows the open till and can sell.
 */
export default function TerminalPage() {
  const { t } = useTranslation("pos");
  const { me, enabledUnits } = useSession();
  const qc = useQueryClient();
  const online = useOnline();
  useOutbox();                                    // starts sending any sales waiting from earlier
  const userId = me?.user_id ?? "";
  const [chosen, setChosen] = useState(() => readText(BRANCH_KEY));

  const orgs = useQuery({
    enabled: !!userId,
    networkMode: "always",                        // must run (and answer from the copy on the device) with no connection
    queryKey: ["pos-terminal", "orgs", userId],
    queryFn: () => networkFirst(orgKey(userId), () => unwrap(api.GET("/api/v1/companies"))),
  });
  const branches = useMemo(() => branchesOf(orgs.data?.data ?? []), [orgs.data]);
  const branch = branches.find((b) => b.id === chosen) ?? branches[0];

  const branchData = useQuery({
    enabled: !!branch && !!userId,
    networkMode: "always",
    queryKey: ["pos-terminal", "branch", userId, branch?.id],
    queryFn: () => networkFirst(branchKey(userId, branch!.id), async () => {
      const [tills, devices] = await Promise.all([
        unwrap(api.GET("/api/v1/pos/tills", { params: { query: { branch_id: branch!.id, status: "open" } } })),
        unwrap(api.GET("/api/v1/pos/devices", { params: { query: { branch_id: branch!.id } } })),
      ]);
      return { till: tills.find((x) => x.cashier_id === userId) ?? null, devices };
    }),
  });

  // When the connection comes back, look again: the till may have been closed in the meantime.
  const wasOnline = useRef(online);
  useEffect(() => {
    if (online && !wasOnline.current) void qc.invalidateQueries({ queryKey: ["pos-terminal", "orgs"] }).then(() => qc.invalidateQueries({ queryKey: ["pos-terminal", "branch"] }));
    wasOnline.current = online;
  }, [online, qc]);

  const till = branchData.data?.data.till ?? undefined;
  const devices = branchData.data?.data.devices ?? [];
  const device = till ? devices.find((d) => d.id === till.device_id) : undefined;

  const canCustomers = useCan("customers.view") && enabledUnits.has("crm");
  const scope = useMemo<CacheScope | null>(() => (branch && userId && till ? {
    userId, branchId: branch.id, locationId: device?.location_id ?? null, customers: canCustomers, payments: enabledUnits.has("payments"),
  } : null), [branch, userId, till, device?.location_id, canCustomers, enabledUnits]);
  const terminalCache = useTerminalCache(scope);

  const pick = (id: string) => { setChosen(id); writeText(BRANCH_KEY, id); };
  const failed = orgs.error ?? branchData.error;

  if (orgs.isLoading || (branch && branchData.isLoading)) {
    return <Frame><Centered><div className="w-full max-w-md"><SkeletonRows rows={4} cols={1} /></div></Centered></Frame>;
  }
  if (failed) {
    return <Frame><Centered><ErrorState message={online ? failed.message : t("terminal.sync.neverLoaded")} title={t("terminal.loadFailed")} onRetry={() => { void orgs.refetch(); void branchData.refetch(); }} /></Centered></Frame>;
  }
  if (!branch) return <Frame><Centered><EmptyState title={t("terminal.noBranch")} hint={t("terminal.noBranchHint")} /></Centered></Frame>;
  if (!till) {
    return (
      <Frame info={branch.name}>
        <OpenTill branches={branches} branch={branch} onBranch={pick} devices={devices.filter((d) => d.status === "active")} offline={!online || !!branchData.data?.fromCache} />
      </Frame>
    );
  }
  return <Selling key={till.id} till={till} device={device} branch={branch} cacheState={terminalCache} />;
}
