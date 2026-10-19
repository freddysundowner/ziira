import { useCallback, useRef } from "react";

import { api, Combobox, unwrap, useTranslation } from "@/sdk";

import type { Project } from "../types";

/** Look a project up by code or name as the person types. `onChange` receives the whole project (or null when cleared). */
export function ProjectPicker({ companyId, value, label, onChange, activeOnly = true, clientId, clearable, invalid, id }: {
  companyId: string; value: string; label?: string; onChange: (project: Project | null) => void; activeOnly?: boolean; clientId?: string; clearable?: boolean; invalid?: boolean; id?: string;
}) {
  const { t } = useTranslation("timebilling");
  const seen = useRef(new Map<string, Project>());
  const search = useCallback(async (text: string) => {
    const rows = await unwrap(api.GET("/api/v1/timebilling/projects", {
      params: { query: { company_id: companyId, client_id: clientId, status: activeOnly ? "active" : undefined, search: text.trim() || undefined, limit: 30 } },
    }));
    rows.forEach((p) => seen.current.set(p.id, p));
    return rows.map((p) => ({ value: p.id, label: `${p.code} · ${p.name}`, hint: p.client_name }));
  }, [companyId, clientId, activeOnly]);
  return (
    <Combobox id={id} value={value} selectedLabel={label} search={search} placeholder={t("pickProject")} clearable={clearable} invalid={invalid}
      onChange={(v) => onChange(v ? seen.current.get(v) ?? null : null)} />
  );
}
