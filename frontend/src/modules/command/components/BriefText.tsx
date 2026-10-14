import { cx } from "@/sdk";

import { layoutBrief } from "../logic";

/** A brief's plain text laid out for reading: title, headed sections, bullets and numbered items. */
export default function BriefText({ body }: { body: string }) {
  const layout = layoutBrief(body);
  return (
    <article className="space-y-4 text-sm">
      <h3 className="text-base font-semibold">{layout.title}</h3>
      {layout.sections.map((s, i) => (
        <section key={i} className="space-y-1.5">
          {s.heading && <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">{s.heading}</h4>}
          <ul className="space-y-1">
            {s.items.map((item, j) => (
              <li key={j} className={cx(item.kind === "bullet" && "list-disc ml-5", item.kind === "numbered" && "ml-5 list-decimal", item.kind === "text" && "text-muted")}>{item.text}</li>
            ))}
          </ul>
        </section>
      ))}
    </article>
  );
}
