import { useParams } from "react-router-dom";

import { api, ErrorState, PageHeader, Skeleton, StatusBadge, unwrap, useMutation, useQuery, useQueryClient, useTranslation, toast } from "@/sdk";

import { CommitStep } from "../components/CommitStep";
import { MapStep } from "../components/MapStep";
import { ReviewStep } from "../components/ReviewStep";
import { Stepper } from "../components/Stepper";
import { UploadStep } from "../components/UploadStep";
import { stepOf } from "../lib/wizard";

const POLL_MS = 1500;

/** The import wizard. A new import starts at the upload; an existing one opens at the step its state says (columns, review, import). */
export default function ImportWizardPage() {
  const { t } = useTranslation("imports");
  const { batchId } = useParams();
  const qc = useQueryClient();
  const batch = useQuery({
    enabled: !!batchId,
    queryKey: ["import", batchId],
    queryFn: () => unwrap(api.GET("/api/v1/imports/batches/{batch_id}", { params: { path: { batch_id: batchId! } } })),
    refetchInterval: (q) => (q.state.data?.status === "committing" ? POLL_MS : false),
  });
  // Going back to the columns just means asking for them again: changing the mapping sends the rows back to unchecked.
  const reopen = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.PUT("/api/v1/imports/batches/{batch_id}/mapping", { params: { path: { batch_id: batchId! } }, body: { columns: batch.data!.mapping } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["import", batchId] }),
    onError: (e) => toast(e.message, "bad"),
  });

  if (!batchId) return <><PageHeader title={t("new")} description={t("hint")} back={{ to: "/imports", label: t("history") }} /><Stepper current={0} /><UploadStep /></>;
  if (batch.error) return <ErrorState title={t("notFound")} message={batch.error.message} onRetry={() => void batch.refetch()} />;
  const b = batch.data;
  if (!b) return <Skeleton className="h-48 w-full" />;
  const step = stepOf(b.status);
  return (
    <>
      <PageHeader title={b.kind_title} description={b.filename} back={{ to: "/imports", label: t("history") }} actions={<StatusBadge status={b.status} />} />
      <Stepper current={step} />
      {step === 1 && <MapStep batch={b} />}
      {step === 2 && <ReviewStep batch={b} onBack={() => reopen.mutate()} />}
      {step === 3 && <CommitStep batch={b} />}
    </>
  );
}
