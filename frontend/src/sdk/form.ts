import { useState } from "react";

import { ApiError } from "./api";

/**
 * Form values as text, with change handlers and the server's per-field messages.
 *
 *   const f = useFormState({ name: "", email: "" });
 *   <Field label="Name" error={f.error("name")}><Input {...f.bind("name")} /></Field>
 *   mutation.mutate(f.values);   // on failure: f.fail(error) shows the server's field messages
 */
export function useFormState<T extends Record<string, string>>(initial: T) {
  const [values, setValues] = useState<T>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = <K extends keyof T>(key: K, value: string) => {
    setValues((v) => ({ ...v, [key]: value }));
    setErrors((e) => (e[key as string] ? { ...e, [key as string]: "" } : e));
  };
  return {
    values,
    set,
    bind: (key: keyof T & string) => ({ value: values[key], onChange: (e: { target: { value: string } }) => set(key, e.target.value) }),
    error: (key: string) => errors[key] || null,
    fail: (error: unknown) => setErrors(error instanceof ApiError ? error.fields : {}),
    reset: () => { setValues(initial); setErrors({}); },
    dirty: JSON.stringify(values) !== JSON.stringify(initial),
  };
}

/** "" to null, trimmed: for optional text the API wants as null when empty. */
export const orNull = (value: string): string | null => value.trim() || null;
