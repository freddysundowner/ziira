import { CircleCheck } from "lucide-react";
import { type ReactNode, useLayoutEffect, useRef, useState } from "react";

import { cx } from "@/sdk";

type State = "empty" | "clear" | "shown";

/**
 * The box around one Home widget.
 * - A widget with nothing to render leaves the box out altogether.
 * - A widget that marks its text `data-clear` ("Nothing waiting") shrinks to a one-line "all clear" row at the end of its grid.
 * - `tile` is the compact number tile of the first row: a small label over the number; `wide` (a tile with several figures) takes two columns where the tiles are narrow.
 * Content that arrives later (a loaded query) changes the state, so the box comes back.
 */
export function WidgetCard({ title, tile = false, wide = false, children }: { title?: string; tile?: boolean; wide?: boolean; children: ReactNode }) {
  const body = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<State>("shown");
  useLayoutEffect(() => {
    const el = body.current;
    if (!el) return;
    const check = () => setState(el.childElementCount === 0 && !el.textContent?.trim() ? "empty" : el.querySelector("[data-clear]") ? "clear" : "shown");
    check();
    const watch = new MutationObserver(check);
    watch.observe(el, { childList: true, subtree: true, characterData: true });
    return () => watch.disconnect();
  }, []);
  const clear = state === "clear";
  return (
    <div hidden={state === "empty"} className={cx("min-w-0", wide && !clear && "min-[420px]:col-span-2 min-[1600px]:col-span-1", clear && "order-last col-span-full")} data-widget={state}>
      <section className={cx("h-full min-w-0 rounded-xl [overflow-wrap:anywhere] border border-line bg-surface shadow-card", clear ? "flex items-center gap-2.5 px-3.5 py-2" : tile ? "overflow-hidden p-3 [&_.text-2xl]:text-lg [&_.text-3xl]:text-xl sm:[&_.text-2xl]:text-2xl sm:[&_.text-3xl]:text-3xl" : "p-4")}>
        {clear && <CircleCheck className="h-4 w-4 shrink-0 text-ok" aria-hidden />}
        {title && <h2 className={cx(clear ? "shrink-0 text-sm font-medium" : tile ? "mb-1 text-xs font-medium uppercase tracking-wide text-muted" : "mb-3 text-sm font-semibold")}>{title}</h2>}
        <div ref={body} className={clear ? "min-w-0 flex-1 text-sm text-muted" : undefined}>{children}</div>
      </section>
    </div>
  );
}
