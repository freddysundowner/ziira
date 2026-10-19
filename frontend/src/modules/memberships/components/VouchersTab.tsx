import { Gift, Search } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, DataTable, Drawer, Field, formatDate, Input, Modal, money, NumberInput, Pager, Select, toast, unwrap, useCan, useCurrency, useMutation, usePagedList,
  useQueryClient, useTranslation, today,
} from "@/sdk";

import { CustomerPicker, useDeskBranch } from "../hooks";

type Account = Awaited<ReturnType<typeof lookup>>;
const lookup = (companyId: string, code: string) => unwrap(api.GET("/api/v1/memberships/vouchers/lookup", { params: { query: { company_id: companyId, code } } }));
const TONE = { active: "ok", used: "neutral", void: "bad", expired: "neutral" } as const;

/** Gift vouchers and credit: sell a voucher, find one by code, void one, give credit by hand. */
export function VouchersTab() {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const canManage = useCan("memberships.manage");
  const canAdjust = useCan("memberships.credits");
  const { companyId, branchId } = useDeskBranch("");
  const currency = useCurrency(companyId);
  const [kind, setKind] = useState("");
  const [activeOnly, setActiveOnly] = useState(false);
  const [selling, setSelling] = useState(false);
  const [giving, setGiving] = useState(false);
  const [voiding, setVoiding] = useState<Account | null>(null);
  const [code, setCode] = useState("");
  const [found, setFound] = useState<Account | null>(null);
  const [amount, setAmount] = useState("");
  const [buyer, setBuyer] = useState("");
  const [recipient, setRecipient] = useState("");
  const [expires, setExpires] = useState("");
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [giveTo, setGiveTo] = useState("");
  const [giveKind, setGiveKind] = useState<"promo" | "referral">("promo");

  const list = usePagedList(["memberships", "vouchers", companyId, kind, activeOnly], (limit, offset) =>
    unwrap(api.GET("/api/v1/memberships/vouchers", { params: { query: { company_id: companyId, kind: (kind || undefined) as "gift" | undefined, active_only: activeOnly, limit, offset } } })), 25, !!companyId);
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["memberships", "vouchers"] }); };
  const fail = (e: unknown) => toast((e as Error).message, "bad");

  const find = useMutation({ meta: { silent: true }, onError: (e) => { setFound(null); fail(e); }, mutationFn: () => lookup(companyId, code.trim()), onSuccess: setFound });
  const sell = useMutation({
    meta: { silent: true }, onError: fail,
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/vouchers", { body: { company_id: companyId, branch_id: branchId, amount, purchaser_customer_id: buyer || null, recipient_customer_id: recipient || null, expires_on: expires || null, note: note.trim() || null } })),
    onSuccess: (a) => { refresh(); setSelling(false); setAmount(""); setBuyer(""); setRecipient(""); setExpires(""); setNote(""); toast(t("vouchers.sold", { code: a.code ?? "" }), "ok"); },
  });
  const voidIt = useMutation({
    meta: { silent: true }, onError: fail,
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/vouchers/{account_id}/void", { params: { path: { account_id: voiding?.id ?? "" } }, body: { reason: reason.trim() } })),
    onSuccess: () => { refresh(); setVoiding(null); setReason(""); setFound(null); toast(t("vouchers.voided"), "ok"); },
  });
  const give = useMutation({
    meta: { silent: true }, onError: fail,
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/credits/give", { body: { customer_id: giveTo, amount, note: note.trim(), kind: giveKind } })),
    onSuccess: () => { refresh(); setGiving(false); setAmount(""); setGiveTo(""); setNote(""); toast(t("vouchers.given"), "ok"); },
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (code.trim().length >= 3) find.mutate(); }}>
          <Field label={t("vouchers.lookup")}><Input value={code} maxLength={30} placeholder={t("vouchers.codePlaceholder")} onChange={(e) => setCode(e.target.value)} /></Field>
          <Button type="submit" variant="secondary" loading={find.isPending} disabled={code.trim().length < 3}><Search className="h-4 w-4" />{t("vouchers.find")}</Button>
        </form>
        <div className="ml-auto flex gap-2">
          {canAdjust && <Button variant="secondary" onClick={() => { setNote(""); setAmount(""); setGiving(true); }}><Gift className="h-4 w-4" />{t("vouchers.giveCredit")}</Button>}
          {canManage && <Button onClick={() => { setNote(""); setAmount(""); setSelling(true); }}>{t("vouchers.sell")}</Button>}
        </div>
      </div>
      {found && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface p-4">
          <div>
            <p className="font-mono text-lg font-bold">{found.code}</p>
            <p className="text-sm text-muted">{t(`extras.kinds.${found.kind}`, found.kind)} · {found.customer_name ?? found.purchaser_name ?? ""} · {found.expires_on ? t("expiresOn", { date: formatDate(found.expires_on) }) : t("neverExpires")}</p>
          </div>
          <div className="flex items-center gap-3"><span className="text-2xl font-bold">{money(found.balance, currency)}</span><Badge tone={TONE[found.status as keyof typeof TONE] ?? "neutral"}>{t(`vouchers.status.${found.status}`, found.status)}</Badge>
            {canAdjust && found.status === "active" && <Button variant="danger" size="sm" onClick={() => setVoiding(found)}>{t("vouchers.void")}</Button>}</div>
        </div>
      )}
      <DataTable rows={list.rows} loading={list.query.isLoading || !companyId} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(a) => a.id}
        toolbar={(
          <>
            <Select className="w-44" aria-label={t("vouchers.kind")} value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="">{t("vouchers.allKinds")}</option>{(["gift", "referral", "promo", "points"] as const).map((x) => <option key={x} value={x}>{t(`extras.kinds.${x}`)}</option>)}
            </Select>
            <label className="flex min-h-10 items-center gap-2 text-sm"><input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} />{t("vouchers.activeOnly")}</label>
          </>
        )}
        empty={{ title: t("vouchers.empty"), hint: t("vouchers.emptyHint") }}
        columns={[
          { header: t("vouchers.code"), cell: (a) => <span className="font-mono">{a.code ?? "—"}</span> },
          { header: t("vouchers.kind"), hideBelow: "sm", cell: (a) => t(`extras.kinds.${a.kind}`, a.kind) },
          { header: t("customer"), hideBelow: "md", cell: (a) => a.customer_name ?? a.purchaser_name ?? "—" },
          { header: t("vouchers.balance"), align: "right", cell: (a) => `${money(a.balance, currency)} / ${money(a.initial, currency)}` },
          { header: t("expires"), hideBelow: "lg", cell: (a) => (a.expires_on ? formatDate(a.expires_on) : "—") },
          { header: t("status"), cell: (a) => <Badge tone={TONE[a.status as keyof typeof TONE] ?? "neutral"}>{t(`vouchers.status.${a.status}`, a.status)}</Badge> },
          { header: "", align: "right", cell: (a) => (canAdjust && a.status === "active" && a.kind === "gift" ? <Button size="sm" variant="secondary" onClick={() => setVoiding(a)}>{t("vouchers.void")}</Button> : null) },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />} />

      <Drawer open={selling} onClose={() => setSelling(false)} title={t("vouchers.sell")}
        footer={<><Button variant="secondary" onClick={() => setSelling(false)}>{t("cancel")}</Button><Button loading={sell.isPending} disabled={!(Number(amount) > 0)} onClick={() => sell.mutate()}>{t("vouchers.sell")}</Button></>}>
        <div className="space-y-4">
          <Field label={t("vouchers.amount")} required><NumberInput value={amount} autoFocus onChange={setAmount} /></Field>
          <CustomerPicker value={buyer} onChange={setBuyer} label={t("vouchers.buyer")} />
          <CustomerPicker value={recipient} onChange={setRecipient} label={t("vouchers.recipient")} />
          <Field label={t("vouchers.expires")} hint={t("vouchers.expiresHint")}><Input type="date" min={today()} value={expires} onChange={(e) => setExpires(e.target.value)} /></Field>
          <Field label={t("note")}><Input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
        </div>
      </Drawer>

      <Modal open={giving} onClose={() => setGiving(false)} title={t("vouchers.giveCredit")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setGiving(false)}>{t("cancel")}</Button><Button loading={give.isPending} disabled={!giveTo || !(Number(amount) > 0) || !note.trim()} onClick={() => give.mutate()}>{t("vouchers.giveCredit")}</Button></>}>
        <div className="space-y-4">
          <p className="text-sm text-muted">{t("vouchers.giveExplain")}</p>
          <CustomerPicker value={giveTo} onChange={setGiveTo} required />
          <Field label={t("vouchers.amount")} required><NumberInput value={amount} onChange={setAmount} /></Field>
          <Field label={t("vouchers.giveKind")}><Select value={giveKind} onChange={(e) => setGiveKind(e.target.value as typeof giveKind)}><option value="promo">{t("extras.kinds.promo")}</option><option value="referral">{t("extras.kinds.referral")}</option></Select></Field>
          <Field label={t("vouchers.why")} required><Input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
        </div>
      </Modal>

      <Modal open={!!voiding} onClose={() => setVoiding(null)} title={t("vouchers.voidTitle", { code: voiding?.code ?? "" })} size="sm"
        footer={<><Button variant="secondary" onClick={() => setVoiding(null)}>{t("cancel")}</Button><Button variant="danger" loading={voidIt.isPending} disabled={!reason.trim()} onClick={() => voidIt.mutate()}>{t("vouchers.void")}</Button></>}>
        <div className="space-y-4">
          <p className="text-sm text-muted">{t("vouchers.voidExplain")}</p>
          <Field label={t("vouchers.why")} required><Input value={reason} maxLength={300} autoFocus onChange={(e) => setReason(e.target.value)} /></Field>
        </div>
      </Modal>
    </div>
  );
}
