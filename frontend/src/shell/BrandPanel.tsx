import { useTranslation, Wordmark } from "@/sdk";

/** Electric line art for the navy brand panel: flowing currents and a node graph in the brand gradient (no external images). */
function ElectricArt() {
  return (
    <svg className="pointer-events-none absolute inset-0 -z-10 h-full w-full opacity-90 max-md:opacity-60" viewBox="0 0 900 1200" preserveAspectRatio="xMidYMid slice" aria-hidden>
      <defs>
        <linearGradient id="el" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#2B7CFF" /><stop offset=".52" stopColor="#24B9C7" /><stop offset="1" stopColor="#10CD8D" /></linearGradient>
        <linearGradient id="elFade" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor="#2B7CFF" stopOpacity="0" /><stop offset=".42" stopColor="#2B7CFF" stopOpacity=".75" /><stop offset=".72" stopColor="#24B9C7" stopOpacity=".8" /><stop offset="1" stopColor="#10CD8D" stopOpacity="0" /></linearGradient>
        <filter id="elGlow" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="8" /></filter>
      </defs>
      <g fill="none" strokeLinecap="round">
        <path d="M450 -70 C610 85 710 145 940 118" stroke="url(#el)" strokeWidth="2" opacity=".48" />
        <path d="M490 -48 C638 92 736 174 930 151" stroke="url(#elFade)" strokeWidth="1.4" opacity=".65" />
        <path d="M545 -35 C665 105 768 199 930 190" stroke="url(#el)" strokeWidth="1" opacity=".38" />
        <path d="M-90 1010 C145 900 280 1040 430 970 S700 765 990 855" stroke="url(#el)" strokeWidth="2.2" opacity=".62" />
        <path d="M-80 1040 C155 935 285 1070 450 1000 S710 795 1000 890" stroke="url(#elFade)" strokeWidth="1.5" opacity=".75" />
        <path d="M-75 1075 C160 970 300 1108 470 1030 S735 830 1000 925" stroke="url(#el)" strokeWidth="1" opacity=".42" />
        <path d="M30 1170 C230 1045 350 1155 510 1080 S760 900 940 955" stroke="url(#elFade)" strokeWidth="1.2" opacity=".45" />
        <path d="M620 340 C700 420 770 430 920 410" stroke="url(#el)" strokeWidth="1.2" opacity=".22" />
      </g>
      <g fill="none" stroke="url(#el)" strokeWidth="1" opacity=".23">
        <path d="M575 270 L660 315 L735 282 L820 330 L900 302" /><path d="M660 315 L675 390 L765 410 L820 330" /><path d="M735 282 L750 220 L835 202 L900 245" />
        <path d="M450 850 L520 810 L590 850 L650 805 L730 830 L800 780 L880 800" /><path d="M520 810 L525 735 L605 700 L650 805" /><path d="M730 830 L750 900 L830 920 L880 800" />
      </g>
      <g fill="#24B9C7" opacity=".8"><circle cx="660" cy="315" r="3" /><circle cx="820" cy="330" r="2.6" /><circle cx="835" cy="202" r="2.4" /><circle cx="590" cy="850" r="2.7" /><circle cx="650" cy="805" r="3" /><circle cx="800" cy="780" r="2.8" /></g>
      <g fill="#10CD8D" opacity=".75"><circle cx="735" cy="282" r="2.3" /><circle cx="765" cy="410" r="2.4" /><circle cx="730" cy="830" r="2.5" /><circle cx="830" cy="920" r="2.4" /></g>
      <g fill="#2B7CFF" opacity=".8"><circle cx="575" cy="270" r="2.6" /><circle cx="605" cy="700" r="2.5" /><circle cx="750" cy="220" r="2.2" /></g>
      <path d="M530 760 C660 690 755 730 910 655" stroke="#2B7CFF" strokeWidth="22" opacity=".07" fill="none" filter="url(#elGlow)" />
    </svg>
  );
}

/**
 * The navy brand panel of the signed-out screens (the owner's login design): electric line art in the brand gradient behind the
 * logo, the headline and a footer. `className` sets where it sits (a column of a grid).
 */
export function BrandPanel({ className = "" }: { className?: string }) {
  const { t } = useTranslation();
  return (
      <section aria-label={t("appName")} className={`relative isolate flex flex-col justify-between overflow-hidden bg-navy px-6 pb-7 pt-6 text-white md:min-h-screen md:p-8 lg:px-[clamp(34px,5vw,78px)] lg:py-11 ${className}`}>
        <div className="absolute inset-0 -z-20" style={{ background: "radial-gradient(ellipse at 12% 85%, rgba(43,124,255,.14), transparent 34%), radial-gradient(ellipse at 90% 22%, rgba(36,185,199,.10), transparent 32%), #0B0F1A" }} />
        <ElectricArt />
        <div className="flex min-h-[42px] items-center"><Wordmark tone="dark" className="h-10 w-auto md:h-14" /></div>
        <div className="max-w-[600px] py-9 md:py-0">
          <p className="max-w-[570px] text-[34px] font-semibold leading-[1.06] tracking-[-0.05em] md:text-[clamp(32px,3.6vw,56px)]">{t("auth.tagline")}</p>
          <p className="mt-4 max-w-[440px] text-sm leading-relaxed text-[#B4C0D4] md:text-[17px] md:leading-[1.7]">{t("auth.subtitle")}</p>
        </div>
        <p className="flex items-center gap-2 text-xs text-[#9AA7BD]"><i className="inline-block h-[7px] w-[7px] rounded-full bg-mint shadow-[0_0_12px_rgba(16,205,141,.4)]" aria-hidden />© {new Date().getFullYear()} Ziira</p>
      </section>
  );
}
