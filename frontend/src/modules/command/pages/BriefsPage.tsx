import { useEffect, useState } from "react";

import { api, ErrorState, PageHeader, SkeletonRows, Tabs, unwrap, useCan, useQuery, useTranslation } from "@/sdk";

import AllSchedules from "../components/AllSchedules";
import BriefHistory from "../components/BriefHistory";
import NoteCard from "../components/NoteCard";
import NoteLinks from "../components/NoteLinks";
import { DEFAULT_NOTE, type NoteDraft, noteFrom } from "../logic";

/** The daily note: one small card, two quiet links, past notes. People who manage others' notes also get a Team tab. */
export default function BriefsPage() {
  const { t } = useTranslation("command");
  const canManage = useCan("briefs.manage");
  const [tab, setTab] = useState<"mine" | "team">("mine");
  const mine = useQuery({ queryKey: ["command", "schedules", "mine"], queryFn: () => unwrap(api.GET("/api/v1/command/schedules/mine")) });
  const [draft, setDraft] = useState<NoteDraft>(DEFAULT_NOTE);
  const [ready, setReady] = useState(false);
  useEffect(() => { if (mine.data && !ready) { setDraft(noteFrom(mine.data)); setReady(true); } }, [mine.data, ready]);

  return (
    <>
      <PageHeader title={t("briefsTitle")} back={{ to: "/intelligence", label: t("backToToday") }} />
      {canManage && <Tabs value={tab} onChange={setTab} tabs={[{ id: "mine", label: t("tabMine") }, { id: "team", label: t("tabTeam") }]} />}
      {canManage && tab === "team" ? <AllSchedules /> : (
        <div className="max-w-2xl space-y-6">
          {mine.error ? <ErrorState message={mine.error.message} onRetry={() => void mine.refetch()} />
            : !mine.data || !ready ? <SkeletonRows rows={3} cols={2} /> : (
              <div className="space-y-3">
                <NoteCard schedules={mine.data} draft={draft} onDraft={setDraft} />
                <NoteLinks channel={draft.channel} />
              </div>
            )}
          <section>
            <h2 className="mb-2 text-sm font-semibold">{t("history")}</h2>
            <BriefHistory />
          </section>
        </div>
      )}
    </>
  );
}
