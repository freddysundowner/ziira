import { Plus, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api, Alert, Button, Checkbox, Drawer, Field, IconButton, Input, money, NumberInput, Select, Textarea, unwrap, useTranslation } from "@/sdk";

import { useClaimsMutation } from "../hooks";
import { blankRow, type EditorRow, hasProblems, rowProblems, rowsFromLines, rowsTotal, toLineBody } from "../lib";
import { LINE_KINDS, PART_CLASSES, type Estimate, type EstimateLine, type Payer } from "../types";

export interface EditorTarget {
  /** A draft to change (a new version is made as a draft first), or null to start a new estimate of `kind`. */
  estimate: Estimate | null;
  kind: "original" | "supplementary";
}

/**
 * Write or change the lines of a draft estimate. Prices include tax. A labour or paint line with no price takes the payer's rate;
 * lines the payer already settled in an earlier version are shown but cannot change.
 */
export function EstimateEditor({ claimId, target, payer, currency, onClose }: { claimId: string; target: EditorTarget | null; payer: Payer | undefined; currency: string | undefined; onClose: () => void }) {
  const { t } = useTranslation("claims");
  const [rows, setRows] = useState<EditorRow[]>([blankRow()]);
  const [notes, setNotes] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [revisionNote, setRevisionNote] = useState("");
  const [terms, setTerms] = useState(false);
  const [tried, setTried] = useState(false);
  const open = target !== null;
  useEffect(() => {
    if (!target) return;
    setTried(false); setTerms(false);
    const base = target.estimate ?? null;
    if (base) {
      setRows(rowsFromLines(base.lines)); setNotes(base.notes ?? ""); setValidUntil(base.valid_until ?? ""); setRevisionNote(base.revision_note ?? "");
    } else {
      setRows([blankRow()]); setNotes(""); setValidUntil(""); setRevisionNote("");
    }
  }, [target]);
  const set = (key: string, patch: Partial<EditorRow>) => setRows((all) => all.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const settled: EstimateLine[] = [];
  const save = useClaimsMutation(async () => {
    const lines = toLineBody(rows);
    if (target?.estimate) {
      return unwrap(api.PATCH("/api/v1/claims/estimates/{estimate_id}", { params: { path: { estimate_id: target.estimate.id } }, body: { lines, notes: notes.trim() || null, valid_until: validUntil || null, revision_note: revisionNote.trim() || null, apply_payer_terms: terms } }));
    }
    return unwrap(api.POST("/api/v1/claims/claims/{claim_id}/estimates", { params: { path: { claim_id: claimId } }, body: {
      kind: target?.kind ?? "original", lines, notes: notes.trim() || null, valid_until: validUntil || null, apply_payer_terms: terms } }));
  }, { silent: true, onDone: () => onClose() });
  const submit = () => { setTried(true); if (!hasProblems(rows)) save.mutate(undefined); };
  const fixed = target?.estimate ? target.estimate.lines.filter((l) => l.locked) : settled;
  const title = target?.estimate ? t("editor.editTitle", { label: target.estimate.label }) : target?.kind === "supplementary" ? t("editor.supplementaryTitle") : t("editor.newTitle");
  return (
    <Drawer open={open} onClose={onClose} title={title}
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={submit}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("editor.hint", { currency: currency ?? "" })}</p>
        {save.error && <Alert tone="bad">{save.error.message}</Alert>}
        {target?.estimate?.previous_id && <Alert tone="info">{t("editor.revisionHint")}</Alert>}
        {rows.map((r, i) => {
          const problems = tried ? rowProblems(r) : [];
          return (
            <fieldset key={r.key} disabled={r.locked} className="space-y-3 rounded-xl border border-line p-3 disabled:bg-sunken/50">
              <legend className="sr-only">{t("editor.line", { n: i + 1 })}</legend>
              <div className="flex items-center gap-2">
                <Select aria-label={t("editor.kind")} className="w-auto" value={r.kind} onChange={(e) => set(r.key, { kind: e.target.value as EditorRow["kind"] })}>
                  {LINE_KINDS.map((k) => <option key={k} value={k}>{t(`kind.${k}`)}</option>)}
                </Select>
                {r.locked && <span className="text-xs text-muted">{t("lines.settled")}</span>}
                <span className="flex-1" />
                {!r.locked && rows.length > 1 && <IconButton label={t("common.remove")} onClick={() => setRows((all) => all.filter((x) => x.key !== r.key))}><X className="h-4 w-4" /></IconButton>}
              </div>
              <Field label={t("editor.description")} error={problems.includes("description") ? t("editor.descriptionNeeded") : null}>
                <Input maxLength={300} value={r.description} invalid={problems.includes("description")} onChange={(e) => set(r.key, { description: e.target.value })} />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label={r.kind === "labour" ? t("editor.hours") : t("editor.quantity")} error={problems.includes("quantity") ? t("editor.quantityNeeded") : null}>
                  <NumberInput value={r.quantity} inputMode="decimal" invalid={problems.includes("quantity")} onChange={(v) => set(r.key, { quantity: v })} />
                </Field>
                <Field label={t("editor.price")} hint={r.kind === "labour" || r.kind === "paint" ? t("editor.priceRate") : undefined} error={problems.includes("price") ? t("editor.priceNeeded") : null}>
                  <NumberInput value={r.unitPrice} inputMode="decimal" invalid={problems.includes("price")} placeholder={r.kind === "labour" || r.kind === "paint" ? t("editor.payerRate") : ""} onChange={(v) => set(r.key, { unitPrice: v })} />
                </Field>
              </div>
              {r.kind === "labour" && (
                <Field label={t("editor.workType")} hint={t("editor.workTypeHint", { types: Object.keys(payer?.labour_rates ?? {}).join(", ") })}>
                  <Input maxLength={40} value={r.workType} list="claims-work-types" onChange={(e) => set(r.key, { workType: e.target.value })} />
                </Field>
              )}
              {r.kind === "parts" && (
                <Field label={t("editor.partClass")}>
                  <Select value={r.partClass} onChange={(e) => set(r.key, { partClass: e.target.value })}>
                    <option value="">{t("editor.partClassNone")}</option>
                    {PART_CLASSES.map((c) => <option key={c} value={c}>{t(`partClass.${c}`)}</option>)}
                  </Select>
                </Field>
              )}
            </fieldset>
          );
        })}
        <datalist id="claims-work-types">{Object.keys(payer?.labour_rates ?? {}).map((k) => <option key={k} value={k} />)}</datalist>
        <Button variant="secondary" size="sm" onClick={() => setRows((all) => [...all, blankRow()])}><Plus className="h-4 w-4" />{t("editor.addLine")}</Button>
        {payer && (Number(payer.parts_discount_pct) > 0 || Number(payer.parts_markup_pct) > 0) && (
          <Checkbox label={t("editor.applyTerms", { discount: payer.parts_discount_pct, markup: payer.parts_markup_pct })} checked={terms} onChange={(e) => setTerms(e.target.checked)} />
        )}
        {target?.estimate?.previous_id ? (
          <Field label={t("editor.revisionNote")} hint={t("editor.revisionNoteHint")}><Textarea maxLength={1000} value={revisionNote} onChange={(e) => setRevisionNote(e.target.value)} /></Field>
        ) : null}
        <Field label={t("editor.notes")} hint={t("editor.notesHint")}><Textarea maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        <Field label={t("editor.validUntil")} hint={t("editor.validUntilHint")}><Input type="date" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} /></Field>
        <p className="tnum rounded-lg bg-sunken px-3 py-2 text-sm font-semibold">{t("editor.total")}: {money(rowsTotal(rows, fixed), currency)}</p>
      </div>
    </Drawer>
  );
}
