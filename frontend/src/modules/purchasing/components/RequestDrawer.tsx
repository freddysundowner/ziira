import { Plus, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";

import { api, Button, Drawer, Field, IconButton, Input, NumberInput, toast, today, unwrap, useCompany, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { isPositive } from "../lib";
import { CompanyBranch } from "./CompanyBranch";
import { useLines } from "./lines";
import { ProductPicker } from "./pickers";

interface Line { key: string; product_id: string; quantity: string; note: string }

/** A request to buy: what is needed, how much, by when. A manager approves it and it then becomes an order. Mount only while open. */
export function RequestDrawer({ onClose, onSaved }: { onClose: () => void; onSaved: (id: string) => void }) {
  const { t } = useTranslation("purchasing");
  const qc = useQueryClient();
  const { company } = useCompany();
  const [chosenCompany, setCompanyId] = useState("");
  const companyId = chosenCompany || company?.id || "";
  const [branchId, setBranchId] = useState("");
  const [neededBy, setNeededBy] = useState("");
  const { lines, add, update, remove } = useLines<Line>(() => ({ product_id: "", quantity: "1", note: "" }), [{ key: crypto.randomUUID(), product_id: "", quantity: "1", note: "" }]);
  const filled = lines.filter((l) => l.product_id);
  const valid = filled.length > 0 && filled.every((l) => isPositive(l.quantity));

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/purchasing/requests", { body: {
      company_id: companyId, branch_id: branchId || null, needed_by: neededBy || null, lines: filled.map((l) => ({ product_id: l.product_id, quantity: l.quantity, note: l.note.trim() || null })) } })),
    onSuccess: (r) => { void qc.invalidateQueries({ queryKey: ["purchasing"] }); toast(t("requestCreated", { number: r.number }), "ok"); onClose(); onSaved(r.id); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Drawer open onClose={onClose} title={t("newRequest")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="request-form" loading={save.isPending} disabled={!valid}>{t("saveDraft")}</Button></>}>
      <form id="request-form" onSubmit={submit} className="space-y-4">
        <CompanyBranch companyId={companyId} branchId={branchId} onCompany={setCompanyId} onBranch={setBranchId} />
        <Field label={t("neededBy")}><Input type="date" min={today()} value={neededBy} onChange={(e) => setNeededBy(e.target.value)} /></Field>
        <div className="space-y-2">
          {lines.map((l) => (
            <div key={l.key} className="space-y-2 rounded-lg border border-line bg-sunken/40 p-3">
              <div className="flex items-end gap-2">
                <Field label={t("product")} className="min-w-0 flex-1"><ProductPicker value={l.product_id} onChange={(v) => update(l.key, { product_id: v })} /></Field>
                <Field label={t("quantity")} className="w-24"><NumberInput value={l.quantity} onChange={(v) => update(l.key, { quantity: v })} /></Field>
                <IconButton label={t("removeLine")} disabled={lines.length === 1} onClick={() => remove(l.key)}><Trash2 className="h-4 w-4" /></IconButton>
              </div>
              <Input aria-label={t("note")} placeholder={t("note")} value={l.note} maxLength={200} onChange={(e) => update(l.key, { note: e.target.value })} />
            </div>
          ))}
        </div>
        <Button variant="secondary" size="sm" onClick={() => add()}><Plus className="h-4 w-4" />{t("addLine")}</Button>
      </form>
    </Drawer>
  );
}
