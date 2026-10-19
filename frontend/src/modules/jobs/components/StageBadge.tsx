import { Badge } from "@/sdk";

import { stageTone } from "../lib";
import type { StageRef } from "../types";

/** A stage's name, coloured by what it means (going on, waiting, finished, over). */
export function StageBadge({ stage }: { stage: Pick<StageRef, "name" | "kind"> }) {
  return <Badge tone={stageTone(stage.kind)}>{stage.name}</Badge>;
}
