/** Shared building blocks so every module looks the same. Keep them small and plain. */
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

const cx = (...parts: (string | false | undefined)[]) => parts.filter(Boolean).join(" ");

export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" }) {
  return (
    <button
      className={cx(
        "rounded-md px-3 py-2 text-sm font-medium disabled:opacity-50",
        variant === "primary" ? "bg-brand text-white hover:bg-brand-dark" : "border border-slate-300 bg-white hover:bg-slate-50",
        className,
      )}
      {...props}
    />
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-1 text-sm">
      <span className="font-medium text-slate-700">{label}</span>
      {children}
    </label>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" {...props} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm" {...props} />;
}

export function Card({ title, children, actions }: { title?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      {(title || actions) && (
        <header className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">{title}</h2>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, actions }: { title: string; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between">
      <h1 className="text-xl font-semibold">{title}</h1>
      {actions}
    </div>
  );
}

export function Table<Row>({
  rows,
  columns,
  empty,
  rowKey,
}: {
  rows: readonly Row[];
  columns: { header: string; cell: (row: Row) => ReactNode }[];
  empty: string;
  rowKey: (row: Row) => string;
}) {
  if (rows.length === 0) return <p className="py-6 text-center text-sm text-slate-500">{empty}</p>;
  return (
    <table className="w-full text-left text-sm">
      <thead className="border-b border-slate-200 text-slate-500">
        <tr>{columns.map((c) => <th key={c.header} className="py-2 pr-4 font-medium">{c.header}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={rowKey(row)} className="border-b border-slate-100 last:border-0">
            {columns.map((c) => <td key={c.header} className="py-2 pr-4">{c.cell(row)}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  return children ? <p className="text-sm text-red-600">{children}</p> : null;
}
