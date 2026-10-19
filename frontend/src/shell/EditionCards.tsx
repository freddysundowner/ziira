import { Blocks, Landmark, ShoppingCart, Sparkles, Truck, type LucideIcon } from "lucide-react";

import { cx, useTranslation, type Edition } from "@/sdk";

const ICONS: Record<string, LucideIcon> = { retail: ShoppingCart, distribution: Truck, books: Landmark, intelligence: Sparkles, full: Blocks };

/** "What do you need?": one card per edition. Words come from the translations by edition id, falling back to the server's own title and pitch. */
export function EditionCards({ choices, value, onChange, wide, title = true }: {
  choices: readonly Edition[]; value: string; onChange: (id: string) => void;
  /** Cards side by side on a wide screen (the full-page sign-up). */
  wide?: boolean;
  /** Show the question and the reassurance above the cards (the wizard has its own heading). */
  title?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <fieldset className="space-y-2">
      <legend className={title ? "mb-1 text-lg font-semibold" : "sr-only"}>{t("edition.need")}</legend>
      {title && <p className="mb-2 text-sm text-muted">{t("edition.later")}</p>}
      <div className={cx(wide ? "gap-2" : "gap-3", wide ? "grid sm:grid-cols-2 lg:grid-cols-3" : "space-y-2")}>
      {choices.map((e) => {
        const Icon = ICONS[e.id] ?? Blocks;
        const on = value === e.id;
        return (
          <label key={e.id} className={cx("flex cursor-pointer items-center gap-2.5 rounded-lg border text-sm focus-within:ring-2 focus-within:ring-brand", wide ? "px-3 py-2.5" : "p-3", on ? "border-brand bg-brand/5" : "border-line hover:bg-sunken")}>
            <input type="radio" name="edition" className="sr-only" checked={on} onChange={() => onChange(e.id)} />
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-brand-soft text-brand-strong"><Icon className="h-4 w-4" /></span>
            <span className="min-w-0">
              <span className="block font-medium">{t(`edition.${e.id}.title`, { defaultValue: e.title })}</span>
              <span className={cx("block text-muted", wide && "line-clamp-2 text-xs")}>{t(`edition.${e.id}.pitch`, { defaultValue: e.pitch })}</span>
            </span>
          </label>
        );
      })}
      </div>
    </fieldset>
  );
}
