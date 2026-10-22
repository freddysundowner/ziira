import type { SlotProps } from "@/sdk";

import { WaitingBox } from "./WaitingBox";

/** Home box: jobs waiting for parts. */
export default function WaitingPartsWidget({ variant }: SlotProps) {
  return <WaitingBox kind="parts" variant={variant} />;
}
