import { CircleHelp } from "lucide-react";

import { useTranslation } from "@/sdk";

/** "What does this mean?": a small panel that explains the few words that cannot be avoided. */
export default function Glossary({ terms }: { terms: readonly string[] }) {
  const { t } = useTranslation("intel");
  return (
    <details className="group relative inline-block text-sm">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-md px-1.5 py-1 text-muted hover:text-ink">
        <CircleHelp className="h-4 w-4" aria-hidden />{t("glossary.open")}
      </summary>
      <dl className="absolute right-0 z-20 mt-1 w-80 max-w-[85vw] space-y-2 rounded-xl border border-line bg-surface p-3 text-sm shadow-pop">
        {terms.map((term) => (
          <div key={term}>
            <dt className="font-medium">{t(`glossary.${term}.word`)}</dt>
            <dd className="text-muted">{t(`glossary.${term}.means`)}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
