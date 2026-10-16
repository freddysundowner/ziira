import { type ReactNode, useState } from "react";

import type { FormApi } from "./form";
import { EMPTY, type FieldKey, type Values } from "./state";

/** Test helper: a real, stateful FormApi around a step, so typing changes the answers; errors show for fields already touched. */
export function Harness({ initial, errors = {}, children }: {
  initial?: Partial<Values>; errors?: Partial<Record<FieldKey, string>>; children: (form: FormApi) => ReactNode;
}) {
  const [values, setValues] = useState<Values>({ ...EMPTY, ...initial });
  const form: FormApi = {
    values, set: (key, value) => setValues((v) => ({ ...v, [key]: value })), blur: () => undefined, error: (key) => errors[key] ?? null,
  };
  return <>{children(form)}</>;
}
