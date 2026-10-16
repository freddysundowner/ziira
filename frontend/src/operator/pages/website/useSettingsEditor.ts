import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { toast, useTranslation, useUnsavedWarning } from "@/sdk";

import { opApi, OperatorApiError, opUnwrap } from "../../client";
import { useChange } from "../../stepUp";
import { KEYS, useSettings } from "./api";
import { changes, type Form, type FormValue, quickProblems, type SettingsTab, TAB_KEYS, toForm } from "./model";

/** One tab's settings as a form: loaded once, edited locally, saved as only what changed, with the server's own messages beside the fields. */
export function useSettingsEditor(tab: SettingsTab) {
  const { t } = useTranslation("operator");
  const queryClient = useQueryClient();
  const keys = TAB_KEYS[tab];
  const query = useSettings();
  const [form, setForm] = useState<Form | null>(null);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (query.data && form === null) setForm(toForm(keys, query.data.values));
  }, [query.data, form, keys]);

  const current = useMemo<Form>(() => form ?? {}, [form]);
  const changed = useMemo(() => (form ? changes(keys, form, query.data?.values) : {}), [form, keys, query.data]);
  const problems = useMemo(() => quickProblems(keys, current), [keys, current]);
  const dirty = Object.keys(changed).length > 0;
  useUnsavedWarning(dirty);

  const save = useChange(
    () => opUnwrap(opApi.PUT("/api/v1/operator/site/settings", { body: { values: changed } })),
    {
      onSuccess: (result) => {
        queryClient.setQueryData(KEYS.settings, result);
        void queryClient.invalidateQueries({ queryKey: KEYS.status });
        void queryClient.invalidateQueries({ queryKey: KEYS.validate });
        setForm(toForm(keys, result.values));
        setServerErrors({});
        toast(t("website.saved"), "ok");
      },
      onError: (error) => {
        const fields = error instanceof OperatorApiError ? (error.body.fields as Record<string, string> | undefined) : undefined;
        if (fields) {
          setServerErrors(fields);
          toast(t("website.fixFields"), "bad");
        } else toast(error.message, "bad");
      },
    },
  );

  const errorFor = (key: string): string | null => serverErrors[key] ?? (problems[key] ? t(`website.problems.${problems[key]}`) : null);
  const set = (key: string, value: FormValue) => {
    setForm((f) => ({ ...(f ?? {}), [key]: value }));
    setServerErrors((e) => (key in e ? Object.fromEntries(Object.entries(e).filter(([k]) => k !== key)) : e));
  };
  const setLocal = (key: string, locale: string, value: string) => {
    const now = current[key];
    set(key, { ...(typeof now === "object" ? now : {}), [locale]: value });
  };

  return {
    query, form: current, ready: form !== null, dirty, hasProblems: Object.keys(problems).length > 0, errorFor, set, setLocal,
    save: () => save.mutate(undefined), saving: save.isPending,
    discard: () => { setForm(toForm(keys, query.data?.values)); setServerErrors({}); },
  };
}

export type SettingsEditor = ReturnType<typeof useSettingsEditor>;
