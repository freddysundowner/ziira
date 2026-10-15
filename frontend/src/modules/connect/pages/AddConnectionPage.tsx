import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  Alert, api, Button, Card, Checkbox, ErrorState, Field, FormGrid, Input, PageHeader, Select, Skeleton, unwrap, useCompany, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { BranchMapping } from "../components/BranchMapping";
import { OAuthButton } from "../components/OAuthButton";
import { when } from "../components/RunsTable";
import { UploadFlow } from "../components/UploadFlow";
import { connectionPath, groupKinds, type Kind, sortEntities } from "../logic";
import { keepPendingFile } from "../uploadLogic";
import { DropFirst } from "../components/DropFirst";

type Step = "choose" | "details" | "connect" | "read" | "branches";

/** The wizard: choose a system, give the details, test it, read it for the first time, map its branches. */
export default function AddConnectionPage() {
  const { t } = useTranslation("connect");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { companies, company } = useCompany();
  const kinds = useQuery({ queryKey: ["connect", "kinds"], queryFn: () => unwrap(api.GET("/api/v1/connect/kinds")) });
  const [step, setStep] = useState<Step>("choose");
  const [kind, setKind] = useState<Kind | null>(null);
  const [companyId, setCompanyId] = useState("");
  const [name, setName] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [auto, setAuto] = useState(false);
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const chosenCompany = companyId || company?.id || "";
  const isFile = kind?.freshness === "on_upload";

  const create = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/connect/connections", { body: { company_id: chosenCompany, kind: kind!.kind, name, config: values, auto_create_branches: auto } })),
    onSuccess: (c) => { setConnectionId(c.id); setStep("connect"); void queryClient.invalidateQueries({ queryKey: ["connect"] }); },
  });

  if (kinds.isLoading) return <Skeleton className="h-64 w-full" />;
  if (kinds.error || !kinds.data) return <ErrorState message={kinds.error?.message} onRetry={() => void kinds.refetch()} />;
  const steps: Step[] = isFile ? ["choose", "details", "connect", "branches"] : ["choose", "details", "connect", "read", "branches"];

  return (
    <>
      <PageHeader title={t("wizard.title")} back={{ to: "/connect", label: t("title") }} />
      <ol className="mb-5 flex flex-wrap gap-2 text-xs">
        {steps.map((s, i) => (
          <li key={s} className={`rounded-full px-3 py-1 ${s === step ? "bg-brand-soft font-medium text-brand-strong" : "bg-sunken text-muted"}`}>{i + 1}. {t(`wizard.step.${s === "connect" && isFile ? "upload" : s}`)}</li>
        ))}
      </ol>

      {step === "choose" && (
        <div className="space-y-5">
          <DropFirst kinds={kinds.data} onFound={(k, file, password) => { keepPendingFile(file, password); setKind(k); setName(k.title); setStep("details"); }} />
          {groupKinds(kinds.data).map((g) => (
            <Card key={g.group} title={t(`group.${g.kinds[0].freshness === "on_upload" ? "files" : "erp"}`)}>
              <div className="grid gap-3 sm:grid-cols-2">
                {g.kinds.map((k) => (
                  <button key={k.kind} type="button" onClick={() => { setKind(k); setName(k.title); setStep("details"); }}
                    className="rounded-xl border border-line p-3 text-left transition-colors hover:border-brand/50 hover:bg-sunken">
                    <span className="block font-medium">{k.title}</span>
                    <span className="mt-1 block text-sm text-muted">{k.description}</span>
                    <span className="mt-2 block text-xs text-muted">{t("wizard.gives")}: {sortEntities(k.entities).map((e) => t(`entity.${e}`, { defaultValue: e })).join(", ")}</span>
                  </button>
                ))}
              </div>
            </Card>
          ))}
        </div>
      )}

      {step === "details" && kind && (
        <form onSubmit={(e) => { e.preventDefault(); create.mutate(); }} className="space-y-4">
          <Card title={kind.title} description={t("wizard.howTo")}>
            <div className="space-y-4">
              <Alert tone="info">{kind.how_to || kind.description}</Alert>
              <FormGrid>
                <Field label={t("wizard.name")} required><Input value={name} onChange={(e) => setName(e.target.value)} required minLength={2} maxLength={80} /></Field>
                {companies.length > 1 && (
                  <Field label={t("company")}><Select value={chosenCompany} onChange={(e) => setCompanyId(e.target.value)}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
                )}
                {kind.config_fields.map((f) => (
                  <Field key={f.name} label={f.label} required={f.required && !kind.needs_oauth} hint={f.secret ? `${t("wizard.secretNote")} ${f.help}` : f.help}>
                    <Input type={f.secret ? "password" : "text"} autoComplete="off" placeholder={f.example} value={values[f.name] ?? ""}
                      required={f.required && !kind.needs_oauth} onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))} />
                  </Field>
                ))}
              </FormGrid>
              <Checkbox checked={auto} onChange={(e) => setAuto(e.target.checked)} label={t("wizard.autoBranches")} />
              <p className="text-xs text-muted">{t("wizard.readOnly")}</p>
              {create.error && <Alert tone="bad">{create.error.message}</Alert>}
            </div>
          </Card>
          <div className="flex justify-between">
            <Button variant="secondary" onClick={() => setStep("choose")}>{t("back")}</Button>
            <Button type="submit" loading={create.isPending} disabled={!chosenCompany || name.trim().length < 2}>{t("wizard.create")}</Button>
          </div>
        </form>
      )}

      {step === "connect" && kind && connectionId && (isFile
        ? <FileStep connectionId={connectionId} kind={kind} companyId={chosenCompany} onNext={() => setStep("branches")} />
        : <ConnectStep connectionId={connectionId} kind={kind} onNext={() => setStep("read")} />)}
      {step === "read" && connectionId && <ReadStep connectionId={connectionId} onNext={() => setStep("branches")} />}
      {step === "branches" && connectionId && (
        <div className="space-y-4">
          <Card title={t("wizard.step.branches")}><BranchMapping connectionId={connectionId} companyId={chosenCompany} /></Card>
          <div className="flex justify-end"><Button onClick={() => navigate(connectionPath(connectionId))}>{t("wizard.finish")}</Button></div>
        </div>
      )}
    </>
  );
}

function FileStep({ connectionId, kind, companyId, onNext }: { connectionId: string; kind: Kind; companyId: string; onNext: () => void }) {
  const { t } = useTranslation("connect");
  return (
    <div className="space-y-4">
      <UploadFlow connectionId={connectionId} kind={kind} companyId={companyId} />
      <div className="flex justify-end"><Button variant="secondary" onClick={onNext}>{t("next")}</Button></div>
    </div>
  );
}

function ConnectStep({ connectionId, kind, onNext }: { connectionId: string; kind: Kind; onNext: () => void }) {
  const { t } = useTranslation("connect");
  const test = useMutation({ meta: { silent: true }, mutationFn: () => unwrap(api.POST("/api/v1/connect/connections/{connection_id}/test", { params: { path: { connection_id: connectionId } } })) });
  return (
    <div className="space-y-4">
      {kind.needs_oauth && <Card title={t("oauth.title")}><OAuthButton connectionId={connectionId} kind={kind.kind} title={kind.title} /></Card>}
      <Card title={t("wizard.test")} description={t("wizard.testHint")}>
        <div className="space-y-3">
          <Button variant="secondary" loading={test.isPending} onClick={() => test.mutate()}>{t("wizard.testButton")}</Button>
          {test.error && <Alert tone="bad">{test.error.message}</Alert>}
          {test.data && <Alert tone={test.data.ok ? "ok" : "bad"}>{test.data.message}</Alert>}
        </div>
      </Card>
      <div className="flex justify-end"><Button disabled={!test.data?.ok} onClick={onNext}>{t("wizard.firstRead")}</Button></div>
    </div>
  );
}

/** Queues the first read and watches the history until every entity of it has finished. */
function ReadStep({ connectionId, onNext }: { connectionId: string; onNext: () => void }) {
  const { t } = useTranslation("connect");
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const start = useMutation({ meta: { silent: true }, mutationFn: () => unwrap(api.POST("/api/v1/connect/connections/{connection_id}/sync", { params: { path: { connection_id: connectionId } }, body: { full: false } })), onSuccess: () => setStartedAt(Date.now() - 5000) });
  const progress = useQuery({
    queryKey: ["connect", "first-read", connectionId], enabled: startedAt !== null, refetchInterval: 2000,
    queryFn: async () => ({
      runs: await unwrap(api.GET("/api/v1/connect/connections/{connection_id}/runs", { params: { path: { connection_id: connectionId }, query: { limit: 40, offset: 0 } } })),
      connection: await unwrap(api.GET("/api/v1/connect/connections/{connection_id}", { params: { path: { connection_id: connectionId } } })),
    }),
  });
  const runs = (progress.data?.runs ?? []).filter((r) => startedAt !== null && new Date(r.started_at).getTime() >= startedAt);
  const connection = progress.data?.connection;
  const finished = connection?.last_sync_at ? new Date(connection.last_sync_at).getTime() >= (startedAt ?? Infinity) : false;
  return (
    <div className="space-y-4">
      <Card title={t("wizard.firstRead")} description={t("wizard.firstReadHint")}>
        <div className="space-y-3">
          {startedAt === null && <Button loading={start.isPending} onClick={() => start.mutate()}>{t("wizard.readNow")}</Button>}
          {start.error && <Alert tone="bad">{start.error.message}</Alert>}
          {startedAt !== null && !finished && <p className="text-sm text-muted" role="status">{t("wizard.reading")}</p>}
          {finished && connection?.last_error && <Alert tone="bad">{connection.last_error}</Alert>}
          {finished && !connection?.last_error && <Alert tone="ok">{t("wizard.readDone")}</Alert>}
          <ul className="space-y-1 text-sm">
            {runs.map((r) => (
              <li key={r.id} className="flex flex-wrap justify-between gap-2 border-b border-line py-1">
                <span>{t(`entity.${r.entity}`, { defaultValue: r.entity })} <span className="text-muted">({t(`run.${r.status}`)})</span></span>
                <span className="tnum text-muted">{t("wizard.counts", { read: r.records_read, news: r.records_new, skipped: r.records_skipped })} · {when(r.finished_at)}</span>
              </li>
            ))}
          </ul>
        </div>
      </Card>
      <div className="flex justify-end"><Button disabled={!finished} onClick={onNext}>{t("next")}</Button></div>
    </div>
  );
}
