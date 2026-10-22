import type { SlotProps } from "@/sdk";

import { WaitingBox } from "./WaitingBox";

/** Home box: jobs waiting for approval. */
export default function WaitingApprovalWidget({ variant }: SlotProps) {
  return <WaitingBox kind="approval" variant={variant} />;
}
