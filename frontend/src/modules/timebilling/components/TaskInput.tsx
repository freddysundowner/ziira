import { useId } from "react";

import { Input, useTranslation } from "@/sdk";

import { useActivities } from "../hooks";

/** The "what did you work on" box: free text, with the business's activity names offered as suggestions. */
export function TaskInput({ companyId, value, onChange, id, placeholder }: { companyId: string; value: string; onChange: (value: string) => void; id?: string; placeholder?: string }) {
  const { t } = useTranslation("timebilling");
  const list = useId();
  const activities = useActivities(companyId);
  return (
    <>
      <Input id={id} value={value} maxLength={120} list={activities.data?.length ? list : undefined} autoComplete="off" onChange={(e) => onChange(e.target.value)} placeholder={placeholder ?? t("taskHint")} />
      {!!activities.data?.length && <datalist id={list}>{activities.data.map((a) => <option key={a.id} value={a.name} />)}</datalist>}
    </>
  );
}
