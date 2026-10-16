import { type ReactNode, useLayoutEffect, useRef, useState } from "react";

import { Card } from "@/sdk";

/**
 * The box around one Home widget. A widget may have nothing to say (no billing notice, nothing waiting): it then renders nothing, and the
 * box is left out instead of showing as an empty card. Content that arrives later (a loaded query) brings the box back.
 */
export function WidgetCard({ title, children }: { title?: string; children: ReactNode }) {
  const body = useRef<HTMLDivElement>(null);
  const [empty, setEmpty] = useState(false);
  useLayoutEffect(() => {
    const el = body.current;
    if (!el) return;
    const check = () => setEmpty(el.childElementCount === 0 && !el.textContent?.trim());
    check();
    const watch = new MutationObserver(check);
    watch.observe(el, { childList: true, subtree: true, characterData: true });
    return () => watch.disconnect();
  }, []);
  return (
    <div hidden={empty} className="min-w-0" data-widget={empty ? "empty" : "shown"}>
      <Card className="h-full min-w-0" title={title}><div ref={body}>{children}</div></Card>
    </div>
  );
}
