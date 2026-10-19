import { useEffect, useState } from "react";

import { Button, Field, Input, Textarea, toast, useTranslation } from "@/sdk";

/** The booking page's address, ready to share: a link to copy, a QR code to print, and a snippet to put on a website. */
export function ShareLink({ slug }: { slug: string }) {
  const { t } = useTranslation("bookings");
  const link = `${window.location.origin}/book/${slug}`;
  const [qr, setQr] = useState("");
  useEffect(() => {
    let live = true;
    void import("qrcode").then((m) => m.toDataURL(link, { margin: 1, width: 192 })).then((url) => { if (live) setQr(url); }).catch(() => { if (live) setQr(""); });
    return () => { live = false; };
  }, [link]);
  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); toast(t("settings.copied"), "ok"); } catch { toast(t("settings.copyFailed"), "bad"); }
  };
  const button = `<a href="${link}" style="display:inline-block;padding:10px 18px;background:#1a73e8;color:#fff;border-radius:8px;text-decoration:none">${t("settings.embedButton")}</a>`;
  return (
    <section className="space-y-4 rounded-xl border border-line bg-sunken p-4" aria-label={t("settings.share")}>
      <h3 className="text-sm font-semibold">{t("settings.share")}</h3>
      <div className="flex flex-col gap-4 sm:flex-row">
        {qr && <img src={qr} width={128} height={128} alt={t("settings.qrAlt")} className="h-32 w-32 rounded-lg border border-line bg-white p-1" />}
        <div className="min-w-0 flex-1 space-y-3">
          <Field label={t("settings.link")}>
            <div className="flex gap-2"><Input readOnly value={link} onFocus={(e) => e.currentTarget.select()} /><Button variant="secondary" onClick={() => void copy(link)}>{t("settings.copy")}</Button></div>
          </Field>
          <Field label={t("settings.embed")} hint={t("settings.embedHint")}>
            <div className="flex gap-2"><Textarea readOnly className="min-h-[64px] font-mono text-xs" value={button} onFocus={(e) => e.currentTarget.select()} /><Button variant="secondary" onClick={() => void copy(button)}>{t("settings.copy")}</Button></div>
          </Field>
        </div>
      </div>
    </section>
  );
}
