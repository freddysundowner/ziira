import { useId } from "react";

/** The connected-dots mark in the brand gradient: works on light and dark (the gradient is bright enough on both). */
export function BrandMark({ className = "h-5 w-auto" }: { className?: string }) {
  const id = useId();
  return (
    <svg viewBox="0 0 72 40" className={className} aria-hidden focusable="false">
      <defs><linearGradient id={id} x1="4" y1="0" x2="68" y2="0" gradientUnits="userSpaceOnUse"><stop offset="0" stopColor="#2B7CFF" /><stop offset=".52" stopColor="#24B9C7" /><stop offset="1" stopColor="#10CD8D" /></linearGradient></defs>
      <path d="M18 10Q36 19 54 10V30Q36 21 18 30Z" fill={`url(#${id})`} />
      <circle cx="18" cy="20" r="14" fill={`url(#${id})`} /><circle cx="54" cy="20" r="14" fill={`url(#${id})`} />
    </svg>
  );
}

/** The wordmark: the mark in a gradient tile is not used; the name is set in Inter so it follows the theme's ink colour. */
export function BrandName({ name, className = "" }: { name: string; className?: string }) {
  return <span className={`text-[21px] font-bold leading-none tracking-[-0.04em] text-ink ${className}`}>{name}</span>;
}

/** The Ziira logo for a dark panel (white letters) or a light one (navy letters), exactly as supplied with the theme. */
export function Wordmark({ tone = "light", className = "h-9 w-auto" }: { tone?: "light" | "dark"; className?: string }) {
  return <img src={tone === "dark" ? "/brand/ziira-logo-on-dark.png" : "/brand/ziira-logo-on-light.png"} alt="Ziira" className={`${className} object-contain`} />;
}

/** The dots mark of the Ziira logo on its own (collapsed sidebar, small spots). */
export function BrandTile({ size = 32, className = "" }: { size?: number; className?: string }) {
  return <img src="/brand/ziira-mark.png" alt="" aria-hidden width={size} height={size} style={{ width: size, height: size }} className={`shrink-0 object-contain ${className}`} />;
}

/** The Ziira logo as supplied with the theme (letters plus gradient dots): navy letters on light surfaces, white on dark. */
export function BrandWord({ className = "h-7" }: { className?: string }) {
  return (
    <>
      <img src="/brand/ziira-logo-on-light.png" alt="Ziira" className={`${className} w-auto object-contain dark:hidden`} />
      <img src="/brand/ziira-logo-on-dark.png" alt="" aria-hidden className={`${className} hidden w-auto object-contain dark:block`} />
    </>
  );
}
