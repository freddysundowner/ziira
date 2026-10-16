import { useState } from "react";

import { readStored, writeStored } from "@/sdk/storage";

const KEY = "ziira.intel.technical";

/** The expert switch: show technical names, codes, limits and raw numbers. Remembered per browser; off by default. */
export function useTechnical(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(readStored(KEY) === "1");
  return [on, (next) => { setOn(next); writeStored(KEY, next ? "1" : null); }];
}
