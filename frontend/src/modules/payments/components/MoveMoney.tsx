import { useEffect } from "react";

import {
  api, Button, Drawer, Field, FormGrid, Input, NumberInput, orNull, Select, today, toast, unwrap, useCompany, useFormState, useMutation, useQueryClient,
  useTranslation,
} from "@/sdk";

import { usePaymentAccounts } from "./usePaymentAccounts";

export type MoveKind = "settlement" | "deposit";

/** Move money between accounts: mobile money paid into the bank (a settlement), or a branch's cash taken to the bank. */
export function MoveMoney({ kind, onClose }: { kind: MoveKind | null; onClose: () => void }) {
  const { t } = useTranslation("payments");
  const qc = useQueryClient();
  const { company, companies } = useCompany();
  const accounts = usePaymentAccounts({ enabled: !!kind });
  const f = useFormState({ from_account_id: "", to_account_id: "", bank_account_id: "", branch_id: "", amount: "", fee: "", business_date: today(), reference: "" });
  const { reset } = f;
  useEffect(() => { if (kind) reset(); }, [kind]); // eslint-disable-line react-hooks/exhaustive-deps

  const list = accounts.data ?? [];
  const banks = list.filter((a) => a.kind === "bank");
  const from = list.filter((a) => a.kind !== "cash" || kind === "settlement");
  const bank = banks.find((a) => a.id === f.values.bank_account_id);
  const companyId = bank?.company_id ?? company?.id ?? "";
  const branches = companies.find((c) => c.id === companyId)?.branches ?? [];

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const v = f.values;
      if (kind === "settlement") {
        return unwrap(api.POST("/api/v1/payments/settlements", { body: {
          from_account_id: v.from_account_id, to_account_id: v.to_account_id, amount: v.amount, fee: v.fee || "0", business_date: v.business_date || null, reference: v.reference.trim() } }));
      }
      return unwrap(api.POST("/api/v1/payments/cash-deposits", { body: {
        company_id: companyId, branch_id: v.branch_id || branches[0]?.id || "", bank_account_id: v.bank_account_id, amount: v.amount, business_date: orNull(v.business_date), reference: v.reference.trim() } }));
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["payments"] });
      toast(t(kind === "settlement" ? "settlementRecorded" : "depositRecorded"), "ok");
      onClose();
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });

  return (
    <Drawer open={!!kind} onClose={onClose} title={kind === "deposit" ? t("cashDeposit") : t("settlement")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="move-money" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="move-money" className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <p className="text-sm text-muted">{t(kind === "deposit" ? "cashDepositHint" : "settlementHint")}</p>
        {kind === "settlement" ? (
          <>
            <Field label={t("fromAccount")} required error={f.error("from_account_id")}>
              <Select {...f.bind("from_account_id")} required><option value="">{t("choose")}</option>{from.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select>
            </Field>
            <Field label={t("toAccount")} required error={f.error("to_account_id")}>
              <Select {...f.bind("to_account_id")} required><option value="">{t("choose")}</option>{banks.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select>
            </Field>
          </>
        ) : (
          <>
            <Field label={t("bankAccount")} required error={f.error("bank_account_id")}>
              <Select {...f.bind("bank_account_id")} required><option value="">{t("choose")}</option>{banks.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select>
            </Field>
            <Field label={t("branch")} required error={f.error("branch_id")}>
              <Select value={f.values.branch_id || branches[0]?.id || ""} onChange={(e) => f.set("branch_id", e.target.value)}>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select>
            </Field>
          </>
        )}
        <FormGrid>
          <Field label={t("amount")} required error={f.error("amount")}><NumberInput value={f.values.amount} onChange={(v) => f.set("amount", v)} required /></Field>
          {kind === "settlement" && <Field label={t("fee")} hint={t("feeHint")} error={f.error("fee")}><NumberInput value={f.values.fee} onChange={(v) => f.set("fee", v)} /></Field>}
          <Field label={t("date")} error={f.error("business_date")}><Input type="date" {...f.bind("business_date")} max={today()} /></Field>
        </FormGrid>
        <Field label={t("reference")} required hint={t("referenceHint")} error={f.error("reference")}><Input {...f.bind("reference")} required maxLength={60} /></Field>
      </form>
    </Drawer>
  );
}
