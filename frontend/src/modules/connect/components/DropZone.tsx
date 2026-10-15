import { Upload } from "lucide-react";
import { useRef, useState } from "react";

import { Alert, useTranslation } from "@/sdk";

import { ACCEPT, MAX_MB, refuseFile } from "../uploadLogic";

/** A big place to drop a file (or click to choose one). Checks the type and size before anything is sent. */
export function DropZone({ onFile, busy, picturesOk, statement }: { onFile: (file: File) => void; busy?: boolean; picturesOk?: boolean; statement: boolean }) {
  const { t } = useTranslation("connect");
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [refused, setRefused] = useState<"type" | "size" | null>(null);

  const take = (file: File | undefined) => {
    if (!file) return;
    const why = refuseFile(file);
    setRefused(why);
    if (!why) onFile(file);
  };

  return (
    <div className="space-y-2">
      <div
        role="button" tabIndex={0} aria-label={t(statement ? "upload.dropStatement" : "upload.dropFile")} aria-disabled={busy}
        onClick={() => !busy && input.current?.click()}
        onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !busy) { e.preventDefault(); input.current?.click(); } }}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); if (!busy) take(e.dataTransfer.files[0]); }}
        className={`flex cursor-pointer flex-col items-center gap-2 rounded-2xl border-2 border-dashed px-4 py-10 text-center transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand ${over ? "border-brand bg-brand-soft" : "border-line bg-surface hover:bg-sunken"} ${busy ? "opacity-60" : ""}`}
      >
        <Upload className="h-8 w-8 text-brand" aria-hidden />
        <p className="text-lg font-medium">{t(statement ? (picturesOk === false ? "upload.dropStatementNoPhoto" : "upload.dropStatement") : "upload.dropFile")}</p>
        <p className="text-sm text-muted">{t("upload.orClick", { mb: MAX_MB })}</p>
        <input ref={input} type="file" accept={ACCEPT} hidden aria-label={t("upload.pick")} onChange={(e) => { take(e.target.files?.[0]); e.target.value = ""; }} />
      </div>
      {refused && <Alert tone="bad">{t(refused === "type" ? "upload.refusedType" : "upload.refusedSize", { mb: MAX_MB })}</Alert>}
    </div>
  );
}
