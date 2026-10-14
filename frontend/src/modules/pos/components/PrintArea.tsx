import { type ReactNode } from "react";
import { createPortal } from "react-dom";

const PRINT_CSS = `
.print-root { display: none; }
@media print {
  body > *:not(.print-root) { display: none !important; }
  .print-root { display: block; background: #fff; color: #000; }
  .print-root * { color: #000 !important; border-color: #000 !important; background: transparent !important; }
  @page { margin: 8mm; }
}`;

/**
 * Content that exists only on paper: it sits beside the app and shows when the page is printed, while everything else
 * is hidden. Render it while a printable view is open and call window.print().
 */
export function PrintArea({ children }: { children: ReactNode }) {
  return createPortal(<div className="print-root"><style>{PRINT_CSS}</style>{children}</div>, document.body);
}

/** The narrow, monospaced page a receipt or day report prints on (a till roll). */
export function Sheet({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`mx-auto w-full max-w-[80mm] font-mono text-xs leading-relaxed ${className}`}>{children}</div>;
}

export function Rule() {
  return <hr className="my-2 border-t border-dashed border-line" />;
}

export function Row({ left, right, strong }: { left: ReactNode; right?: ReactNode; strong?: boolean }) {
  return (
    <div className={`flex justify-between gap-3 ${strong ? "font-bold" : ""}`}>
      <span className="min-w-0 break-words">{left}</span>
      {right !== undefined && <span className="tnum shrink-0 text-right">{right}</span>}
    </div>
  );
}
