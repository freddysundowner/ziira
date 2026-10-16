import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Field, FormGrid, Input, Modal, Select, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { useChange } from "../../stepUp";
import { KEYS } from "./api";
import { LEGAL_SLUGS, slugFrom } from "./model";

/** Starts a page: blank, or from a legal outline (clearly a template: it cannot be published until completed). */
export function NewPageModal({ locales, onClose, onCreated }: { locales: string[]; onClose: () => void; onCreated: (id: string) => void }) {
  const { t } = useTranslation("operator");
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<"legal" | "content">("legal");
  const [locale, setLocale] = useState(locales[0] ?? "en");
  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [template, setTemplate] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const create = useChange(
    async () => {
      let body = "";
      let pageTitle = title.trim();
      if (kind === "legal" && template && LEGAL_SLUGS.includes(slug)) {
        const starters = await opUnwrap(opApi.GET("/api/v1/operator/site/pages/starters", { params: { query: { locale } } }));
        const starter = starters.find((s) => s.slug === slug);
        if (starter) { body = starter.body_md; pageTitle = pageTitle || starter.title; }
      }
      return opUnwrap(opApi.POST("/api/v1/operator/site/pages", { body: { slug, locale, kind, title: pageTitle, body_md: body } }));
    },
    {
      onSuccess: (page) => {
        void queryClient.invalidateQueries({ queryKey: KEYS.pages });
        void queryClient.invalidateQueries({ queryKey: KEYS.validate });
        toast(t("website.pages.created"), "ok");
        onCreated(page.id);
      },
      onError: (e) => setError(e.message),
    },
  );
  const ready = slug.length > 0 && (title.trim().length > 0 || (kind === "legal" && template && LEGAL_SLUGS.includes(slug)));

  return (
    <Modal open onClose={onClose} title={t("website.pages.new")} size="md"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button loading={create.isPending} disabled={!ready} onClick={() => { setError(null); create.mutate(undefined); }}>{t("website.pages.create")}</Button></>}>
      <div className="space-y-4">
        <FormGrid>
          <Field label={t("website.pages.kind")}>
            <Select value={kind} onChange={(e) => setKind(e.target.value as "legal" | "content")}>
              <option value="legal">{t("website.pages.kinds.legal")}</option>
              <option value="content">{t("website.pages.kinds.content")}</option>
            </Select>
          </Field>
          <Field label={t("website.pages.language")}>
            <Select value={locale} onChange={(e) => setLocale(e.target.value)}>{locales.map((l) => <option key={l} value={l}>{l.toUpperCase()}</option>)}</Select>
          </Field>
        </FormGrid>
        {kind === "legal" && (
          <Field label={t("website.pages.legalChoice")} hint={t("website.pages.templateHint")}>
            <Select value={LEGAL_SLUGS.includes(slug) ? slug : ""} onChange={(e) => { setSlug(e.target.value); if (e.target.value) setTitle(""); }}>
              <option value="">{t("website.pages.otherLegal")}</option>
              {LEGAL_SLUGS.map((s) => <option key={s} value={s}>{t(`website.pages.legalNames.${s}`)}</option>)}
            </Select>
          </Field>
        )}
        {kind === "legal" && LEGAL_SLUGS.includes(slug) && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={template} onChange={(e) => setTemplate(e.target.checked)} className="h-4 w-4 accent-[rgb(var(--brand))]" />
            {t("website.pages.useTemplate")}
          </label>
        )}
        <Field label={t("website.pages.title")}><Input value={title} onChange={(e) => { setTitle(e.target.value); if (kind === "content" || !LEGAL_SLUGS.includes(slug)) setSlug(slugFrom(e.target.value)); }} /></Field>
        <Field label={t("website.pages.slug")} hint={t("website.pages.slugHint")} error={slug && !/^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug) ? t("website.pages.slugBad") : null}>
          <Input value={slug} onChange={(e) => setSlug(e.target.value)} className="font-mono" />
        </Field>
        {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      </div>
    </Modal>
  );
}
