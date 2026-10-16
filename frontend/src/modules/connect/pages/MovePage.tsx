import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api, Alert, ErrorState, PageHeader, Skeleton, unwrap, useMutation, useQuery, useTranslation } from "@/sdk";
import type { Schemas } from "@/sdk";

import { MoveChooseStep } from "../components/MoveChooseStep";
import { MovePreviewStep } from "../components/MovePreviewStep";
import { MoveRunStep } from "../components/MoveRunStep";
import { defaultKinds, type MoveKind } from "../moveLogic";

type Step = "choose" | "preview" | "run";
type Plan = Schemas["PlanOut"];
interface Draft { asOf?: string; unit?: string; taxCode?: string; locations?: Record<string, string> }

/** Move to Ziira Core: choose what to bring over from the connected system, check exactly what would happen, then watch it happen. */
export default function MovePage() {
  const { t } = useTranslation("connect");
  const { connectionId = "" } = useParams();
  const path = { params: { path: { connection_id: connectionId } } };
  const options = useQuery({ queryKey: ["connect", "move-options", connectionId], queryFn: () => unwrap(api.GET("/api/v1/connect/connections/{connection_id}/move/options", path)) });
  const connection = useQuery({ queryKey: ["connect", "connection", connectionId], queryFn: () => unwrap(api.GET("/api/v1/connect/connections/{connection_id}", path)) });
  // The unit and tax lists belong to Products; someone who may not read them types the codes instead.
  const units = useQuery({ queryKey: ["products", "uoms"], queryFn: () => unwrap(api.GET("/api/v1/products/uoms")), retry: false });
  const taxCodes = useQuery({ queryKey: ["products", "tax-codes"], queryFn: () => unwrap(api.GET("/api/v1/products/tax-codes")), retry: false });
  const [step, setStep] = useState<Step>("choose");
  const [picked, setPicked] = useState<MoveKind[] | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [plan, setPlan] = useState<Plan | null>(null);
  const [moveId, setMoveId] = useState<string | null>(null);
  const running = options.data?.running_move_id;

  useEffect(() => { if (running && !moveId) { setMoveId(running); setStep("run"); } }, [running, moveId]);

  const body = () => {
    const o = options.data!;
    const kinds = picked ?? defaultKinds(o.kinds, o.source_counts);
    return {
      kinds, as_of: draft.asOf ?? o.as_of, unit: draft.unit || (units.data?.length === 1 ? units.data[0].code : null),
      tax_code: draft.taxCode || (taxCodes.data?.length === 1 ? taxCodes.data[0].code : null), locations: draft.locations ?? {},
    };
  };
  const preview = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/connect/connections/{connection_id}/move/preview", { ...path, body: body() })),
    onSuccess: (p) => { setPlan(p); setStep("preview"); },
  });
  const start = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/connect/connections/{connection_id}/move", { ...path, body: body() })),
    onSuccess: (m) => { setMoveId(m.id); setStep("run"); },
  });

  if (options.isLoading || connection.isLoading) return <Skeleton className="h-64 w-full" />;
  if (options.error || !options.data) return <ErrorState message={options.error?.message} onRetry={() => void options.refetch()} />;
  const o = options.data;
  const chosen = picked ?? defaultKinds(o.kinds, o.source_counts);
  const current = body();
  const choice = { asOf: current.as_of, unit: current.unit ?? "", taxCode: current.tax_code ?? "", locations: draft.locations ?? {} };
  const steps: Step[] = ["choose", "preview", "run"];
  const again = () => { setMoveId(null); setPlan(null); setPicked(null); setDraft({}); setStep("choose"); void options.refetch(); };

  return (
    <>
      <PageHeader title={t("move.title")} description={t("move.subtitle", { name: connection.data?.name ?? "" })} back={{ to: `/connect/connections/${connectionId}`, label: connection.data?.name ?? t("title") }} />
      <ol className="mb-5 flex flex-wrap gap-2 text-xs">
        {steps.map((s, i) => <li key={s} aria-current={s === step ? "step" : undefined} className={`rounded-full px-3 py-1 ${s === step ? "bg-brand-soft font-medium text-brand-strong" : "bg-sunken text-muted"}`}>{i + 1}. {t(`move.steps.${s}`)}</li>)}
      </ol>
      {step === "choose" && (
        <>
          {preview.error && <Alert tone="bad" className="mb-4">{preview.error.message}</Alert>}
          <MoveChooseStep connectionId={connectionId} options={o} chosen={chosen} onChosen={setPicked} choice={choice} units={units.data} taxCodes={taxCodes.data}
            onChoice={(c) => setDraft({ asOf: c.asOf, unit: c.unit, taxCode: c.taxCode, locations: c.locations })} busy={preview.isPending} onNext={() => preview.mutate()} />
        </>
      )}
      {step === "preview" && plan && <MovePreviewStep plan={plan} busy={start.isPending} error={start.error?.message} onBack={() => setStep("choose")} onConfirm={() => start.mutate()} />}
      {step === "run" && moveId && <MoveRunStep moveId={moveId} connectionId={connectionId} onAgain={again} />}
    </>
  );
}
