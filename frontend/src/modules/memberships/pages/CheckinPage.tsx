import { Camera, CloudOff, Maximize, RefreshCw, ScanLine } from "lucide-react";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Alert, Badge, Button, cx, EmptyState, ErrorState, PageHeader, Skeleton, Stat, StatGrid, useCurrency, useTranslation } from "@/sdk";

import { CameraScan } from "../components/CameraScan";
import { cameraScanSupported } from "../components/camera";
import { PersonPhoto } from "../components/PersonPhoto";
import { RecentList } from "../components/RecentList";
import { ResultPanel } from "../components/ResultPanel";
import { useDesk, useRoster, useSuggestions, useTodayAndRecent } from "../components/useDesk";
import type { Suggestion } from "../components/useDesk";
import { TermsDialog } from "../components/TermsDialog";
import { clockTime } from "../gymLogic";
import { useDeskBranch, useOnline } from "../hooks";
import { rosterIsValid } from "../offline";
import { kioskPath } from "../public";

/** The front desk: type a name or number, or scan a card, and see at once whether the person may come in. Works offline. */
export default function CheckinPage() {
  const { t } = useTranslation("memberships");
  const { companyId, branchId, branches, field, company } = useDeskBranch("");
  const currency = useCurrency(companyId);
  const online = useOnline();
  const input = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");
  const [active, setActive] = useState(0);
  const [scanning, setScanning] = useState(false);
  const [terms, setTerms] = useState(false);
  const desk = useDesk(companyId, branchId);
  const live = useSuggestions(companyId, branchId, text);
  const roster = useRoster(companyId, branchId);
  const stats = useTodayAndRecent(companyId, branchId);

  const choices: Suggestion[] = desk.choices ?? (text.trim().length >= 2 ? live.data ?? [] : []);
  const listOpen = choices.length > 0;
  useEffect(() => setActive(0), [choices.length, text]);
  useEffect(() => { input.current?.focus(); }, [branchId]);

  const refocus = () => window.setTimeout(() => input.current?.focus(), 0);
  const send = async (value: string, highlighted?: Suggestion, method: "desk" | "scan" = "desk") => {
    setText("");
    await desk.submit(value, highlighted, method);
    refocus();
  };
  const choose = async (s: Suggestion) => { setText(""); await desk.pick(s); refocus(); };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" && listOpen) { e.preventDefault(); setActive((i) => Math.min(i + 1, choices.length - 1)); }
    else if (e.key === "ArrowUp" && listOpen) { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Escape") { setText(""); desk.clear(); }
    else if (e.key === "Enter") { e.preventDefault(); void send(text, listOpen ? choices[active] : undefined); }
  };

  const savedRoster = roster.saved;
  const listUsable = rosterIsValid(savedRoster, Date.now());

  if (company && branches.length === 0) return <EmptyState title={t("checkin.noBranch")} hint={t("checkin.noBranchHint")} />;
  if (!company || !branchId) return <Skeleton className="h-40 w-full" />;

  return (
    <>
      <PageHeader title={t("checkinMenu")} description={t("checkin.hint")}
        actions={(
          <>
            {field}
            <Link to={kioskPath} className="inline-flex h-10 items-center gap-2 rounded-lg border border-line bg-surface px-4 text-sm font-semibold shadow-card hover:bg-sunken"><Maximize className="h-4 w-4" />{t("checkin.openKiosk")}</Link>
          </>
        )} />

      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        {!online && <Badge tone="warn"><CloudOff className="h-3 w-3" />{t("checkin.offlineChip")}</Badge>}
        {desk.queue.length > 0 && (
          <button type="button" onClick={() => void desk.sync()} className="inline-flex items-center gap-1 rounded-md bg-info-soft px-2 py-0.5 font-semibold text-info" aria-label={t("checkin.syncNow")}>
            <RefreshCw className="h-3 w-3" />{t("checkin.waiting", { count: desk.queue.length })}
          </button>
        )}
        {savedRoster && <span className="text-muted">{t("checkin.listSaved", { time: clockTime(savedRoster.savedAt) })}</span>}
        {!savedRoster && !roster.loading && <span className="text-warn">{t("checkin.noListYet")}</span>}
        {savedRoster && !listUsable && <span className="text-bad">{t("checkin.listTooOld")}</span>}
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-4">
          <div className="min-w-0 rounded-xl border border-line bg-surface p-4 shadow-card">
            <label htmlFor="checkin-input" className="mb-2 flex min-w-0 items-center gap-2 text-sm font-semibold"><ScanLine className="h-4 w-4" />{t("checkin.inputLabel")}</label>
            <div className="flex gap-2">
              <input id="checkin-input" ref={input} autoFocus autoComplete="off" autoCorrect="off" spellCheck={false} inputMode="search" enterKeyHint="go"
                role="combobox" aria-expanded={listOpen} aria-controls="checkin-choices" aria-autocomplete="list"
                value={text} onChange={(e) => { setText(e.target.value); if (desk.choices) desk.setChoices(null); }} onKeyDown={onKey}
                placeholder={t("checkin.inputPlaceholder")}
                className="h-16 min-w-0 flex-1 rounded-xl border-2 border-line bg-bg px-4 text-2xl font-medium text-ink placeholder:text-muted/70 focus:border-brand focus:outline-none" />
              <Button size="lg" className="h-16 px-6 text-lg" loading={desk.busy} onClick={() => void send(text, listOpen ? choices[active] : undefined)}>{t("checkin.go")}</Button>
              {cameraScanSupported() && (
                <Button size="lg" variant="secondary" className="h-16 px-4" aria-label={t("checkin.scanCamera")} onClick={() => setScanning(true)}><Camera className="h-6 w-6" /><span className="hidden sm:inline">{t("checkin.scanCamera")}</span></Button>
              )}
            </div>
            {listOpen && (
              <ul id="checkin-choices" role="listbox" aria-label={t("checkin.matches")} className="mt-3 divide-y divide-line overflow-hidden rounded-lg border border-line">
                {choices.map((s, i) => (
                  <li key={s.key} role="option" aria-selected={i === active}>
                    <button type="button" onClick={() => void choose(s)} onMouseEnter={() => setActive(i)}
                      className={cx("flex min-h-14 w-full items-center gap-3 px-3 py-2 text-left", i === active ? "bg-brand-soft" : "hover:bg-sunken")}>
                      <PersonPhoto name={s.name} size="sm" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{s.name}</span>
                        <span className="block truncate text-xs text-muted"><span className="font-mono">{s.number}</span>{s.phone ? ` · ${s.phone}` : ""}{s.plan ? ` · ${s.plan}` : ""}</span>
                      </span>
                      {s.owed > 0 && <Badge tone="bad">{t("checkin.owesShort")}</Badge>}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {live.error && text.trim().length >= 2 && <p role="alert" className="mt-2 text-sm text-bad">{live.error.message}</p>}
            {text.trim().length >= 2 && !live.isFetching && live.data?.length === 0 && !desk.choices && <p className="mt-2 text-sm text-muted">{t("checkin.noMatches")}</p>}
          </div>

          {desk.view
            ? (
              <>
                <ResultPanel view={desk.view} currency={currency} busy={desk.busy} onAcceptTerms={() => setTerms(true)}
                  onOverride={(reason) => { void desk.run({ customerId: desk.view?.customerId, override: reason }).then(refocus); }} />
                <div className="flex justify-end"><Button variant="secondary" onClick={() => { desk.clear(); refocus(); }}>{t("checkin.nextPerson")}</Button></div>
              </>)
            : !listOpen && <Alert tone="info">{t("checkin.ready")}</Alert>}
        </div>

        <div className="min-w-0 space-y-4">
          <StatGrid>
            <Stat label={t("checkin.today")} value={stats.counts.data?.visits ?? 0} loading={stats.counts.isLoading} />
            <Stat label={t("checkin.refused")} value={stats.counts.data?.refused ?? 0} loading={stats.counts.isLoading} tone={(stats.counts.data?.refused ?? 0) > 0 ? "bad" : undefined} />
            <Stat label={t("checkin.letIn")} value={stats.counts.data?.overridden ?? 0} loading={stats.counts.isLoading} />
          </StatGrid>
          {stats.counts.error && <ErrorState message={stats.counts.error.message} onRetry={() => void stats.counts.refetch()} />}
          <RecentList rows={stats.recent.data} loading={stats.recent.isLoading} error={stats.recent.error?.message} onRetry={() => void stats.recent.refetch()} />
        </div>
      </div>

      <CameraScan open={scanning} onClose={() => setScanning(false)} onText={(value) => { setScanning(false); void send(value, undefined, "scan"); }} />
      {desk.view?.customerId && (
        <TermsDialog open={terms} onClose={() => setTerms(false)} customerId={desk.view.customerId} companyId={companyId} personName={desk.view.name}
          onDone={() => { const id = desk.view?.customerId; if (id) void desk.run({ customerId: id }); }} />
      )}
    </>
  );
}
