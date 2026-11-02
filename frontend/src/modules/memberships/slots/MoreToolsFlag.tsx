import { useEffect } from "react";

import { setNavFlag } from "@/sdk";

import { useMoreTools } from "../moreTools";

/** Always mounted (shell.background): lists the extra gym pages in the sidebar only when the owner asked for them. */
export default function MoreToolsFlag() {
  const more = useMoreTools();
  useEffect(() => { setNavFlag("memberships.more", more); }, [more]);
  return null;
}
