import { type FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  Alert, api, Button, Card, EmptyState, ErrorState, Field, FormGrid, Input, NumberInput, orNull, PageHeader, Schemas, Select, Skeleton, toast, today, unwrap, useCompany,
  useCurrency, useMutation, useQuery, useQueryClient, useTranslation, useUnsavedWarning,
} from "@/sdk";

import { useBranches, useLocations, useReasons } from "../hooks";
import { CustomerPicker, useHasCustomers } from "./hooks";
import { LinesEditor } from "./LinesEditor";
import { blankLine, type EditLine, lineBody, linesValid, toEditLines } from "./lib";

export type FormKind = "quotation" | "order" | "invoice";
type Doc = Schemas["DocOut"];

const PATH = { quotation: "/pos/quotations", order: "/pos/orders", invoice: "/pos/invoices" } as const;

/** New quotation, sales order or invoice, or change a draft quotation or order. The server prices, taxes and numbers it. */
export function DocumentFormPage({ kind }: { kind: FormKind }) {
  const { documentId = "" } = useParams();
  const editing = Boolean(documentId) && kind !== "invoice";
  const { t } = useTranslation("pos");
  const hasCustomers = useHasCustomers();
  const existing = useQuery({
    enabled: editing, queryKey: ["pos-doc", kind, documentId],
    queryFn: () => unwrap(kind === "quotation"
      ? api.GET("/api/v1/pos/quotations/{document_id}", { params: { path: { document_id: documentId } } })
      : api.GET("/api/v1/pos/orders/{document_id}", { params: { path: { document_id: documentId } } })),
  });
  if (!hasCustomers) return <EmptyState title={t("docs.needsCustomers")} hint={t("docs.needsCustomersHint")} />;
  if (editing && existing.error) return <ErrorState message={existing.error.message} onRetry={() => void existing.refetch()} />;
  if (editing && !existing.data) return <Skeleton className="h-64 w-full" />;
  return <DocumentForm key={existing.data?.id ?? "new"} kind={kind} existing={existing.data} />;
}

function DocumentForm({ kind, existing }: { kind: FormKind; existing?: Doc }) {
  const { t } = useTranslation("pos");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { company } = useCompany();
  const { branches } = useBranches();
  const [customerId, setCustomerId] = useState(existing?.customer_id ?? "");
  const [branchId, setBranchId] = useState(existing?.branch_id ?? "");
  const effectiveBranch = branchId || branches[0]?.id || "";
  const companyId = existing?.company_id ?? branches.find((b) => b.id === effectiveBranch)?.companyId ?? company?.id;
  const currency = useCurrency(companyId);
  const [lines, setLines] = useState<EditLine[]>(existing ? toEditLines(existing.lines) : [blankLine()]);
  const [reasonId, setReasonId] = useState("");
  const [locationId, setLocationId] = useState(existing?.location_id ?? "");
  const [terms, setTerms] = useState(existing ? String(existing.terms_days) : "");
  const [validUntil, setValidUntil] = useState(existing?.valid_until ?? "");
  const [issueDate, setIssueDate] = useState(today());
  const [notes, setNotes] = useState(existing?.notes ?? "");
  const [touched, setTouched] = useState(false);
  useUnsavedWarning(touched);
  const reasons = useReasons("price_override");
  const locations = useLocations(effectiveBranch);
  const stores = locations.data?.filter((l) => l.is_active) ?? [];
  const needsStore = kind === "invoice" && stores.length > 0;
  // a branch with one store has nowhere else to take goods from
  useEffect(() => { if (!locationId && stores.length === 1) setLocationId(stores[0].id); }, [locationId, stores.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const f = { changed: <A extends unknown[]>(fn: (...a: A) => void) => (...a: A) => { setTouched(true); fn(...a); } };

  const valid = Boolean(customerId) && linesValid(lines) && (!needsStore || Boolean(locationId));
  const termsDays = terms.trim() === "" ? null : Number(terms);

  const save = useMutation({
    meta: { silent: true },
    mutationFn: async (): Promise<{ id: string; number: string }> => {
      const body = lineBody(lines, reasonId);
      const common = { customer_id: customerId, lines: body, branch_id: effectiveBranch || null, location_id: locationId || null, terms_days: termsDays, notes: orNull(notes) };
      if (kind === "invoice") {
        return unwrap(api.POST("/api/v1/pos/invoices", { body: { ...common, issue_date: issueDate || null,
          lines: body.map((l) => ({ ...l })) } }));
      }
      if (existing) {
        const update = { lines: body, notes: notes.trim() };
        return unwrap(kind === "quotation"
          ? api.PUT("/api/v1/pos/quotations/{document_id}", { params: { path: { document_id: existing.id } }, body: { ...update, valid_until: validUntil || null } })
          : api.PUT("/api/v1/pos/orders/{document_id}", { params: { path: { document_id: existing.id } }, body: update }));
      }
      return unwrap(kind === "quotation"
        ? api.POST("/api/v1/pos/quotations", { body: { ...common, valid_until: validUntil || null } })
        : api.POST("/api/v1/pos/orders", { body: common }));
    },
    onSuccess: (doc) => {
      setTouched(false);
      void qc.invalidateQueries({ queryKey: ["pos-docs"] });
      void qc.invalidateQueries({ queryKey: ["pos-doc"] });
      toast(t(`docs.saved.${kind}`, { number: doc.number }), "ok");
      navigate(`${PATH[kind]}/${doc.id}`);
    },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) save.mutate(); };
  const title = existing ? t(`docs.edit.${kind}`, { number: existing.number }) : t(`docs.new.${kind}`);

  return (
    <form onSubmit={submit}>
      <PageHeader back={{ to: existing ? `${PATH[kind]}/${existing.id}` : PATH[kind], label: existing ? existing.number : t(`docs.tabs.${kind}s`) }}
        title={title} description={t(`docs.formHint.${kind}`)}
        actions={<Button type="submit" loading={save.isPending} disabled={!valid}>{t(`docs.save.${kind}`)}</Button>} />
      <div className="space-y-4">
        <Card title={t("details")}>
          <FormGrid cols={3}>
            <Field label={t("docs.customer")} required>
              <CustomerPicker value={customerId} disabled={Boolean(existing)} onChange={f.changed(setCustomerId)} />
            </Field>
            {branches.length > 1 && (
              <Field label={t("branch")}>
                <Select value={effectiveBranch} disabled={Boolean(existing)} onChange={(e) => f.changed(setBranchId)(e.target.value)}>
                  {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                </Select>
              </Field>
            )}
            {kind === "quotation" && <Field label={t("docs.validUntil")} hint={t("docs.validUntilHint")}><Input type="date" min={today()} value={validUntil} onChange={(e) => f.changed(setValidUntil)(e.target.value)} /></Field>}
            {kind === "invoice" && <Field label={t("docs.issueDate")}><Input type="date" max={today()} value={issueDate} onChange={(e) => f.changed(setIssueDate)(e.target.value)} /></Field>}
            {!existing && <Field label={t("docs.termsDays")} hint={t("docs.termsHint")}><NumberInput value={terms} placeholder={t("docs.customerDefault")} onChange={f.changed(setTerms)} /></Field>}
            {!existing && stores.length > 0 && (
              <Field label={t("docs.deliverFrom")} hint={t("docs.deliverFromHint")} required={needsStore}>
                <Select value={locationId} onChange={(e) => f.changed(setLocationId)(e.target.value)}>
                  <option value="">{t(needsStore ? "docs.chooseStore" : "docs.defaultStore")}</option>
                  {stores.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                </Select>
              </Field>
            )}
          </FormGrid>
          <div className="mt-4"><Field label={t("note")}><Input value={notes} maxLength={500} onChange={(e) => f.changed(setNotes)(e.target.value)} /></Field></div>
        </Card>
        <Card title={t("items")}>
          {kind === "invoice" && <Alert tone="warn" className="mb-3">{t("docs.invoiceStockNote")}</Alert>}
          <LinesEditor lines={lines} onChange={f.changed(setLines)} reasonId={reasonId} onReason={f.changed(setReasonId)} reasons={reasons.data ?? []} currency={currency} />
        </Card>
      </div>
    </form>
  );
}
