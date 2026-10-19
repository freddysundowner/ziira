import { Check, ShieldOff } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import {
  api, Alert, type Schemas, Attachments, type AttachedFile, Badge, Button, Card, cx, Field, FormGrid, Input, Textarea, toast, unwrap, useCan, useMutation, useQueryClient,
  useTranslation, orNull,
} from "@/sdk";

import type { Member, Profile } from "../hooks";
import { CustomerPicker } from "../hooks";
import { HouseholdCard } from "./HouseholdCard";
import { MeasurementsCard } from "./MeasurementsCard";
import { TermsCard } from "./TermsCard";

/** Photo, contact and emergency details, household, terms and measurements of one person. */
export function ProfileTab({ customerId, companyId, profile, photos, member }: { customerId: string; companyId: string; profile: Profile | null; photos: AttachedFile[]; member?: Member }) {
  const { t } = useTranslation("memberships");
  if (!profile) return <Alert tone="info">{t("profile.none")}</Alert>;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <ProfileForm profile={profile} customerId={customerId} />
        <div className="space-y-4">
          <PhotoCard profile={profile} photos={photos} customerId={customerId} />
          <BlockCard profile={profile} customerId={customerId} />
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <HouseholdCard profile={profile} customerId={customerId} companyId={companyId} member={member} />
        <TermsCard customerId={customerId} companyId={companyId} personName={profile.customer_name} />
      </div>
      <MeasurementsCard customerId={customerId} />
    </div>
  );
}

function useProfileSave(customerId: string) {
  const qc = useQueryClient();
  const { t } = useTranslation("memberships");
  return useMutation({
    meta: { silent: true },
    mutationFn: (body: Schemas["MemberProfileUpdate"]) =>
      unwrap(api.PATCH("/api/v1/memberships/profiles/by-customer/{customer_id}", { params: { path: { customer_id: customerId } }, body })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["memberships"] }); toast(t("profile.saved"), "ok"); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
}

function ProfileForm({ profile, customerId }: { profile: Profile; customerId: string }) {
  const { t } = useTranslation("memberships");
  const canManage = useCan("memberships.manage");
  const save = useProfileSave(customerId);
  const initial = {
    card: profile.card_number ?? "", ename: profile.emergency_name ?? "", ephone: profile.emergency_phone ?? "", erel: profile.emergency_relation ?? "",
    birth: profile.date_of_birth ?? "", source: profile.source ?? "", tags: profile.tags.join(", "), notes: profile.notes ?? "",
  };
  const [v, setV] = useState(initial);
  const [referrer, setReferrer] = useState(profile.referred_by_customer_id ?? "");
  useEffect(() => { setV(initial); setReferrer(profile.referred_by_customer_id ?? ""); }, [profile.id, profile.card_number, profile.emergency_name, profile.emergency_phone, profile.emergency_relation, profile.date_of_birth, profile.source, profile.notes, profile.tags.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k: keyof typeof initial) => (e: { target: { value: string } }) => setV((x) => ({ ...x, [k]: e.target.value }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate({
      card_number: v.card.trim(), emergency_name: orNull(v.ename), emergency_phone: orNull(v.ephone), emergency_relation: orNull(v.erel),
      date_of_birth: v.birth || null, source: orNull(v.source), referred_by_customer_id: referrer || null, notes: orNull(v.notes),
      tags: v.tags.split(",").map((x) => x.trim()).filter(Boolean).slice(0, 20),
    });
  };
  const off = !canManage;
  return (
    <Card title={t("profile.title")}>
      <form onSubmit={submit} className="space-y-4">
        <FormGrid>
          <Field label={t("profile.memberNumber")}><Input value={profile.number} disabled readOnly /></Field>
          <Field label={t("profile.card")} hint={t("profile.cardHint")}><Input value={v.card} maxLength={40} disabled={off} onChange={set("card")} /></Field>
        </FormGrid>
        <p className="text-sm font-semibold">{t("profile.emergency")}</p>
        <FormGrid cols={3}>
          <Field label={t("profile.emergencyName")}><Input value={v.ename} maxLength={200} disabled={off} onChange={set("ename")} /></Field>
          <Field label={t("profile.emergencyPhone")}><Input type="tel" value={v.ephone} maxLength={40} disabled={off} onChange={set("ephone")} /></Field>
          <Field label={t("profile.emergencyRelation")}><Input value={v.erel} maxLength={60} disabled={off} onChange={set("erel")} /></Field>
        </FormGrid>
        <FormGrid>
          <Field label={t("profile.birthDate")}><Input type="date" value={v.birth} disabled={off} onChange={set("birth")} /></Field>
          <Field label={t("profile.source")} hint={t("profile.sourceHint")}><Input value={v.source} maxLength={100} disabled={off} onChange={set("source")} /></Field>
        </FormGrid>
        <CustomerPicker value={referrer} onChange={setReferrer} label={t("profile.referredBy")} />
        <Field label={t("profile.tags")} hint={t("profile.tagsHint")}><Input value={v.tags} disabled={off} onChange={set("tags")} /></Field>
        <Field label={t("notes")}><Textarea rows={2} maxLength={1000} value={v.notes} disabled={off} onChange={set("notes")} /></Field>
        {canManage && <div className="flex justify-end"><Button type="submit" loading={save.isPending}>{t("save")}</Button></div>}
      </form>
    </Card>
  );
}

function PhotoCard({ profile, photos, customerId }: { profile: Profile; photos: AttachedFile[]; customerId: string }) {
  const { t } = useTranslation("memberships");
  const canManage = useCan("memberships.manage");
  const save = useProfileSave(customerId);
  const pictures = photos.filter((f) => f.kind === "image");
  return (
    <Card title={t("profile.photos")}>
      {canManage && pictures.length > 0 && (
        <div className="mb-4">
          <p className="mb-2 text-sm text-muted">{t("profile.mainPhotoHint")}</p>
          <div className="flex flex-wrap gap-2">
            {pictures.map((f) => {
              const main = f.id === profile.photo_file_id;
              return (
                <button key={f.id} type="button" disabled={save.isPending || main} aria-pressed={main} aria-label={main ? t("profile.mainPhoto") : t("profile.makeMain")} onClick={() => save.mutate({ photo_file_id: f.id })}
                  className={cx("relative h-20 w-20 overflow-hidden rounded-lg border-2", main ? "border-brand" : "border-line hover:border-muted")}>
                  {f.thumb_url ? <img src={f.thumb_url} alt="" className="h-full w-full object-cover" /> : <span className="text-xs">{f.name}</span>}
                  {main && <span className="absolute right-1 top-1 rounded-full bg-brand p-0.5 text-brand-ink"><Check className="h-3 w-3" /></span>}
                </button>
              );
            })}
          </div>
        </div>
      )}
      <Attachments entityType="memberships.profile" entityId={profile.id} />
    </Card>
  );
}

function BlockCard({ profile, customerId }: { profile: Profile; customerId: string }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const canManage = useCan("memberships.manage");
  const [reason, setReason] = useState(profile.block_reason ?? "");
  const block = useMutation({
    meta: { silent: true },
    mutationFn: (blocked: boolean) => unwrap(api.POST("/api/v1/memberships/profiles/by-customer/{customer_id}/block", { params: { path: { customer_id: customerId } }, body: { blocked, reason: blocked ? reason.trim() || null : null } })),
    onSuccess: (_, blocked) => { void qc.invalidateQueries({ queryKey: ["memberships"] }); toast(t(blocked ? "profile.blocked" : "profile.unblocked"), "ok"); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <Card title={t("profile.blockTitle")} description={t("profile.blockHint")}>
      {profile.access_blocked
        ? (
          <div className="space-y-3">
            <p className="flex flex-wrap items-center gap-2 text-sm"><Badge tone="bad">{t("person.entryStopped")}</Badge>{profile.block_reason}</p>
            {canManage && <Button variant="secondary" loading={block.isPending} onClick={() => block.mutate(false)}>{t("profile.allowEntry")}</Button>}
          </div>)
        : canManage
          ? (
            <div className="space-y-3">
              <Field label={t("profile.blockReason")}><Input value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} /></Field>
              <Button variant="danger" loading={block.isPending} disabled={!reason.trim()} onClick={() => block.mutate(true)}><ShieldOff className="h-4 w-4" />{t("profile.stopEntry")}</Button>
            </div>)
          : <p className="text-sm text-muted">{t("profile.notBlocked")}</p>}
    </Card>
  );
}
