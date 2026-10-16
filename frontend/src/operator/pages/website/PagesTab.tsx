import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, type Column, DataTable, formatDate, type Schemas, Select, StatusBadge, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { KEYS, useSettings } from "./api";
import { localesOf, missingLegal, PAGE_STATE_TONE } from "./model";
import { NewPageModal } from "./NewPageModal";
import { PageEditor } from "./PageEditor";

type Page = Schemas["SitePageSummary"];

/** Legal pages and simple content pages: a list with what is live, changed or new, and an editor for each. */
export default function PagesTab() {
  const { t } = useTranslation("operator");
  const [editing, setEditing] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [locale, setLocale] = useState("");
  const [kind, setKind] = useState("");
  const settings = useSettings();
  const pages = useQuery({ queryKey: KEYS.pages, queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/site/pages")) });
  const locales = localesOf(settings.data?.values);

  if (editing) return <PageEditor pageId={editing} onBack={() => setEditing(null)} />;

  const rows = (pages.data ?? []).filter((p) => (!locale || p.locale === locale) && (!kind || p.kind === kind));
  const gaps = locales.map((l) => ({ locale: l, missing: missingLegal(pages.data ?? [], l) })).filter((g) => g.missing.length > 0);
  const columns: Column<Page>[] = [
    { header: t("website.pages.title"), sortValue: (p) => p.title, cell: (p) => <div><button type="button" onClick={() => setEditing(p.id)} className="text-left font-medium hover:underline">{p.title}</button><p className="font-mono text-xs text-muted">{p.locale}/{p.slug}</p></div> },
    { header: t("website.pages.kind"), hideBelow: "sm", cell: (p) => <Badge>{t(`website.pages.kinds.${p.kind}`)}</Badge> },
    { header: t("website.pages.status"), cell: (p) => <div className="flex flex-wrap gap-1"><StatusBadge status={p.status} /><Badge tone={PAGE_STATE_TONE[p.state] ?? "neutral"}>{t(`website.pages.states.${p.state}`)}</Badge></div> },
    { header: t("website.pages.updated"), hideBelow: "md", cell: (p) => <div className="text-sm">{formatDate(p.updated_at, true)}<p className="text-xs text-muted">{p.updated_by ?? ""}</p></div> },
  ];

  return (
    <>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div className="flex gap-2">
          <Select aria-label={t("website.pages.language")} value={locale} onChange={(e) => setLocale(e.target.value)} className="w-32">
            <option value="">{t("website.pages.allLanguages")}</option>
            {locales.map((l) => <option key={l} value={l}>{l.toUpperCase()}</option>)}
          </Select>
          <Select aria-label={t("website.pages.kind")} value={kind} onChange={(e) => setKind(e.target.value)} className="w-36">
            <option value="">{t("website.pages.allKinds")}</option>
            <option value="legal">{t("website.pages.kinds.legal")}</option>
            <option value="content">{t("website.pages.kinds.content")}</option>
          </Select>
        </div>
        <Button onClick={() => setCreating(true)}>{t("website.pages.new")}</Button>
      </div>
      {gaps.length > 0 && !pages.isPending && (
        <Alert tone="warn" className="mb-3">
          <p className="font-medium">{t("website.pages.legalGaps")}</p>
          <ul className="mt-1 list-disc pl-4 text-sm">{gaps.map((g) => <li key={g.locale}>{g.locale.toUpperCase()}: {g.missing.map((s) => t(`website.pages.legalNames.${s}`)).join(", ")}</li>)}</ul>
        </Alert>
      )}
      <Alert tone="info" className="mb-3">{t("website.pages.lawyer")}</Alert>
      <DataTable rows={rows} columns={columns} rowKey={(p) => p.id} loading={pages.isPending} error={pages.isError ? pages.error.message : null}
        onRetry={() => void pages.refetch()} empty={{ title: t("website.pages.empty"), hint: t("website.pages.emptyHint") }} />
      {creating && <NewPageModal locales={locales} onClose={() => setCreating(false)} onCreated={(id) => { setCreating(false); setEditing(id); }} />}
    </>
  );
}
