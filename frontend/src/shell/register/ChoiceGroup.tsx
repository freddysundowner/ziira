import { cx } from "@/sdk";

/** A few mutually exclusive choices shown as large chips (real radio buttons underneath, so the keyboard and screen readers work). Picking the chosen one again clears it when `clearable`. */
export function ChoiceGroup({ name, legend, options, value, onChange, clearable }: {
  name: string; legend: string; options: readonly { value: string; label: string }[]; value: string; onChange: (value: string) => void; clearable?: boolean;
}) {
  return (
    <fieldset>
      <legend className="mb-1 text-[13px] font-medium text-ink">{legend}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => {
          const on = o.value === value;
          return (
            <label key={o.value} className={cx("cursor-pointer rounded-md border px-3 py-1.5 text-[13px] transition-colors focus-within:ring-2 focus-within:ring-brand", on ? "border-brand bg-brand-soft font-medium text-brand-strong" : "border-line bg-surface hover:bg-sunken")}>
              <input
                type="radio" name={name} value={o.value} checked={on} className="sr-only"
                onChange={() => onChange(o.value)}
                onClick={() => { if (clearable && on) onChange(""); }}
              />
              {o.label}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
