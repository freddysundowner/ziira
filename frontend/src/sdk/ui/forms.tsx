import { Children, cloneElement, createContext, forwardRef, isValidElement, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes, useContext, useId } from "react";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes } from "react";

import { cx } from "./cx";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary: "btn-gradient",
  secondary: "border border-line bg-surface text-ink hover:bg-sunken shadow-card [&:disabled:not([aria-busy])]:border-muted/40 [&:disabled:not([aria-busy])]:bg-[rgb(var(--disabled-bg))] [&:disabled:not([aria-busy])]:text-[rgb(var(--disabled-ink))] [&:disabled:not([aria-busy])]:shadow-none",
  ghost: "text-ink hover:bg-sunken [&:disabled:not([aria-busy])]:text-[rgb(var(--disabled-ink))]",
  danger: "bg-bad text-bad-ink hover:opacity-90 shadow-card [&:disabled:not([aria-busy])]:bg-[rgb(var(--disabled-bg))] [&:disabled:not([aria-busy])]:text-[rgb(var(--disabled-ink))] [&:disabled:not([aria-busy])]:shadow-none",
};
const SIZES: Record<Size, string> = { sm: "h-8 px-2.5 text-xs gap-1.5", md: "h-9 px-3.5 text-sm gap-2", lg: "h-11 px-5 text-base gap-2" };

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; loading?: boolean }>(
  function Button({ variant = "primary", size = "md", loading, disabled, className, children, type = "button", ...props }, ref) {
    return (
      <button
        ref={ref}
        type={type}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        className={cx("inline-flex select-none items-center justify-center whitespace-nowrap rounded-lg font-medium transition-colors disabled:cursor-not-allowed", VARIANTS[variant], SIZES[size], className)}
        {...props}
      >
        {loading && <Loader2 className="h-4 w-4 animate-spin" />}
        {children}
      </button>
    );
  },
);

export function IconButton({ label, className, children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button type="button" aria-label={label} title={label} className={cx("inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:bg-sunken hover:text-ink", className)} {...props}>
      {children}
    </button>
  );
}

const CONTROL = "rounded-lg border bg-surface px-3 text-sm text-ink placeholder:text-muted transition-colors disabled:cursor-not-allowed disabled:bg-sunken disabled:text-muted";
/** Controls fill their container unless the caller gives them a width (a toolbar filter): Tailwind cannot be asked which of two widths wins. */
const widthOf = (className?: string) => (className && /(^|\s)(w|min-w|max-w)-/.test(className) ? "" : "w-full");
const controlClass = (invalid?: boolean) => cx(CONTROL, invalid ? "border-bad" : "border-line hover:border-muted/50");

/** The id a Field gives its control when the control is nested in a wrapper (an input with a button beside it). */
const FieldIdContext = createContext<string | undefined>(undefined);

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(function Input({ invalid, className, id, ...props }, ref) {
  const fieldId = useContext(FieldIdContext);
  return <input ref={ref} id={id ?? fieldId} aria-invalid={invalid || undefined} className={cx(controlClass(invalid), widthOf(className), "h-9", className)} {...props} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }>(function Select({ invalid, className, id, ...props }, ref) {
  const fieldId = useContext(FieldIdContext);
  return <select ref={ref} id={id ?? fieldId} aria-invalid={invalid || undefined} className={cx(controlClass(invalid), widthOf(className), "h-9 pr-8", className)} {...props} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }>(function Textarea({ invalid, className, id, ...props }, ref) {
  const fieldId = useContext(FieldIdContext);
  return <textarea ref={ref} id={id ?? fieldId} aria-invalid={invalid || undefined} className={cx(controlClass(invalid), widthOf(className), "min-h-[84px] py-2", className)} {...props} />;
});

/**
 * A label, the control, a hint and an error, wired together for screen readers. Pass the control as a function to get
 * its id, or just pass an Input (the label wraps it).
 */
export function Field({ label, hint, error, required, children, className }: { label: string; hint?: string; error?: string | null; required?: boolean; children: ReactNode; className?: string }) {
  const id = useId();
  return (
    <div className={cx("space-y-1.5", className)}>
      <label htmlFor={id} className="block text-sm font-medium text-ink">
        {label}{required && <span className="ml-0.5 text-bad" aria-hidden>*</span>}
      </label>
      <FieldControl id={id} invalid={!!error}>{children}</FieldControl>
      {error ? <p role="alert" className="text-xs text-bad">{error}</p> : hint ? <p className="text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

function FieldControl({ id, invalid, children }: { id: string; invalid: boolean; children: ReactNode }) {
  const only = Children.count(children) === 1 ? Children.toArray(children)[0] : null;
  if (isValidElement<{ id?: string; invalid?: boolean }>(only) && typeof only.type !== "string") {
    return cloneElement(only, { id: only.props.id ?? id, invalid: only.props.invalid ?? invalid });
  }
  if (isValidElement<{ id?: string }>(only) && (only.type === "input" || only.type === "select" || only.type === "textarea")) {
    return cloneElement(only, { id: only.props.id ?? id });
  }
  return <FieldIdContext.Provider value={id}>{children}</FieldIdContext.Provider>;
}

export function Checkbox({ label, className, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }) {
  return (
    <label className={cx("inline-flex cursor-pointer items-center gap-2 text-sm", className)}>
      <input type="checkbox" className="h-4 w-4 rounded border-line accent-[rgb(var(--brand))]" {...props} />
      {label}
    </label>
  );
}

export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)}
      className={cx("relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50", checked ? "bg-brand" : "bg-line")}>
      <span className={cx("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all", checked ? "left-[18px]" : "left-0.5")} />
    </button>
  );
}

/** A number box for money and quantities: keeps what the person types as text (no rounding surprises) and allows only digits and one point. */
export const NumberInput = forwardRef<HTMLInputElement, Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> & { value: string; onChange: (value: string) => void; invalid?: boolean }>(
  function NumberInput({ value, onChange, className, ...props }, ref) {
    return (
      <Input ref={ref} inputMode="decimal" autoComplete="off" value={value} className={cx("tnum text-right", className)}
        onChange={(e) => { const v = e.target.value.replace(/,/g, "."); if (/^\d*\.?\d*$/.test(v)) onChange(v); }} {...props} />
    );
  },
);
