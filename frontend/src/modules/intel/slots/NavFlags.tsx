import { useEffect } from "react";

import { api, setNavFlag, unwrap, useCompany, useQuery } from "@/sdk";

import { useActionLevel } from "../actions/useActionLevel";

/** Always mounted (shell.background): lists Suggestions in the sidebar when Ziira prepares work, or already has suggestions. */
export default function NavFlags() {
  const { company } = useCompany();
  const level = useActionLevel(company?.id);
  const any = useQuery({ queryKey: ["intel", "proposals", "any"], staleTime: 120_000, queryFn: () => unwrap(api.GET("/api/v1/intel/actions", { params: { query: { limit: 1 } } })) });
  const show = (level ?? 0) >= 3 || (any.data?.length ?? 0) > 0;
  useEffect(() => { setNavFlag("intel.suggestions", show); }, [show]);
  return null;
}
