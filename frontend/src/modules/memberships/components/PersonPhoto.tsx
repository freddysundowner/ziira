import { useEffect, useState } from "react";

import { cx } from "@/sdk";

import { initials } from "../gymLogic";

/** A member's photo (a short-lived signed address), or their initials when there is none or it cannot load. */
export function PersonPhoto({ url, name, size = "md" }: { url?: string | null; name?: string | null; size?: "sm" | "md" | "lg" }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url]);
  const box = { sm: "h-9 w-9 text-xs", md: "h-16 w-16 text-xl", lg: "h-28 w-28 text-4xl" }[size];
  if (url && !failed) {
    return <img src={url} alt="" onError={() => setFailed(true)} className={cx("shrink-0 rounded-full object-cover", box)} />;
  }
  return <span aria-hidden="true" className={cx("flex shrink-0 items-center justify-center rounded-full bg-brand-soft font-semibold text-brand-strong", box)}>{initials(name)}</span>;
}
