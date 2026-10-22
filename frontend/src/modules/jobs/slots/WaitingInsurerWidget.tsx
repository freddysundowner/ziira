import type { SlotProps } from "@/sdk";

import { WaitingBox } from "./WaitingBox";

/** Home box: jobs waiting for insurer. */
export default function WaitingInsurerWidget({ variant }: SlotProps) {
  return <WaitingBox kind="insurer" variant={variant} />;
}
