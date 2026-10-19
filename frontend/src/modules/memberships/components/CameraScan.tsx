import { useEffect, useRef, useState } from "react";

import { Alert, Button, Modal, useTranslation } from "@/sdk";

import { makeDetector } from "./camera";

/** Opens the camera and hands back the first QR code or barcode it reads. */
export function CameraScan({ open, onClose, onText }: { open: boolean; onClose: () => void; onText: (text: string) => void }) {
  const { t } = useTranslation("memberships");
  const video = useRef<HTMLVideoElement>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setProblem(null);
    let stopped = false;
    let stream: MediaStream | null = null;
    let timer: number | undefined;
    const detector = makeDetector();
    void (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
        if (stopped) { stream.getTracks().forEach((x) => x.stop()); return; }
        const el = video.current;
        if (!el || !detector) { setProblem(t("checkin.camera.unsupported")); return; }
        el.srcObject = stream;
        await el.play().catch(() => undefined);
        timer = window.setInterval(() => {
          void detector.detect(el).then((found) => {
            const text = found[0]?.rawValue?.trim();
            if (text && !stopped) { stopped = true; onText(text); }
          }).catch(() => undefined);
        }, 300);
      } catch {
        setProblem(t("checkin.camera.denied"));
      }
    })();
    return () => {
      stopped = true;
      if (timer) window.clearInterval(timer);
      stream?.getTracks().forEach((x) => x.stop());
    };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Modal open={open} onClose={onClose} title={t("checkin.camera.title")} size="sm" footer={<Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>}>
      <div className="space-y-3">
        {problem ? <Alert tone="warn">{problem}</Alert> : <p className="text-sm text-muted">{t("checkin.camera.hint")}</p>}
        <video ref={video} muted playsInline className="aspect-square w-full rounded-lg bg-sunken object-cover" aria-label={t("checkin.camera.title")} />
      </div>
    </Modal>
  );
}
