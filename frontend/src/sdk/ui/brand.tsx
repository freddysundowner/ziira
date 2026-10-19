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

/** The full "ziira" wordmark drawn in strokes (the dots over the i's are the brand mark). `tone` picks white strokes for dark panels. */
export function Wordmark({ tone = "light", className = "h-9 w-auto" }: { tone?: "light" | "dark"; className?: string }) {
  const id = useId();
  const stroke = tone === "dark" ? "#FFFFFF" : "#0B0F1A";
  return (
    <svg viewBox="0 0 320 120" className={className} role="img" aria-label="Ziira">
      <defs><linearGradient id={id} x1="80" y1="0" x2="168" y2="0" gradientUnits="userSpaceOnUse"><stop offset="0" stopColor="#2B7CFF" /><stop offset=".52" stopColor="#24B9C7" /><stop offset="1" stopColor="#10CD8D" /></linearGradient></defs>
      <g fill="none" stroke={stroke} strokeWidth="15" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 54H62L14 102H64" /><path d="M96 56V102" /><path d="M150 56V102" /><path d="M192 56V102M192 76Q196 56 222 57" /><circle cx="262" cy="79" r="23" /><path d="M285 56V102" />
      </g>
      <path d="M96 20Q123 29 150 20V36Q123 28 96 36Z" fill={`url(#${id})`} /><circle cx="96" cy="27" r="13" fill={`url(#${id})`} /><circle cx="150" cy="27" r="13" fill={`url(#${id})`} />
    </svg>
  );
}
