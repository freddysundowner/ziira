import { type ReactNode } from "react";

import { money, quantity, type Schemas } from "@/sdk";

/** Prints only the element with id "pos-receipt": everything else on the screen is hidden on paper. */
export function PrintStyles() {
  return (
    <style>{`@media print {
      body * { visibility: hidden !important; }
      #pos-receipt, #pos-receipt * { visibility: visible !important; }
      #pos-receipt { position: fixed; left: 0; top: 0; width: 100%; max-width: 80mm; margin: 0; padding: 4mm; border: 0; box-shadow: none; background: #fff; color: #000; }
      @page { margin: 4mm; }
    }`}</style>
  );
}

/** The sale's receipt exactly as the server composes it (company, branch, VAT breakdown, footers). */
export function Receipt({ doc, currency }: { doc: Schemas["PrintOut"]; currency: string }) {
  return (
    <div id="pos-receipt" className="mx-auto w-full max-w-[22rem] rounded-lg border border-line bg-surface p-4 font-mono text-xs leading-relaxed text-ink shadow-card">
      <PrintStyles />
      <div className="space-y-0.5 text-center">
        {doc.header.map((h, i) => <p key={i} className={i === 0 ? "text-sm font-bold" : ""}>{h}</p>)}
        <p className="pt-1 font-bold">{doc.title}{doc.is_copy ? " (COPY)" : ""}</p>
        <p>{doc.number}</p>
      </div>
      <Rule />
      {doc.meta.map(([label, value], i) => <Row key={i} left={label ?? ""} right={value ?? ""} />)}
      <Rule />
      <ul className="space-y-1">
        {doc.lines.map((l, i) => (
          <li key={i}>
            <p>{l.description}</p>
            <Row left={`${quantity(l.quantity)} × ${money(l.unit_price, currency)}`} right={money(l.amount, currency)} />
          </li>
        ))}
      </ul>
      <Rule />
      {doc.totals.map((x, i) => <Row key={i} left={x.label} right={money(x.amount, currency)} bold={i === doc.totals.length - 1} />)}
      {doc.vat.length > 0 && (
        <>
          <Rule />
          {doc.vat.map((v, i) => <Row key={i} left={`VAT ${quantity(v.rate)}%  (${money(v.net, currency)})`} right={money(v.tax, currency)} />)}
        </>
      )}
      <Rule />
      {doc.payments.map((x, i) => <Row key={i} left={x.label} right={money(x.amount, currency)} />)}
      {doc.notes.length > 0 && <div className="pt-2">{doc.notes.map((n, i) => <p key={i}>{n}</p>)}</div>}
      {doc.footer.length > 0 && <div className="space-y-0.5 pt-3 text-center">{doc.footer.map((f, i) => <p key={i}>{f}</p>)}</div>}
    </div>
  );
}

const Rule = () => <hr className="my-2 border-dashed border-line" />;

export function Row({ left, right, bold }: { left: ReactNode; right: ReactNode; bold?: boolean }) {
  return <div className={`flex justify-between gap-3 ${bold ? "font-bold" : ""}`}><span>{left}</span><span className="tnum shrink-0">{right}</span></div>;
}
