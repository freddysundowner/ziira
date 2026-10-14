import { Link } from "react-router-dom";

import { useProduct, useSupplier } from "../hooks";

/** A supplier's name from its id (cached, one request per supplier), optionally a link to its page. */
export function SupplierName({ id, link }: { id: string | null | undefined; link?: boolean }) {
  const supplier = useSupplier(id);
  const name = supplier.data?.name ?? (supplier.isError ? "—" : "…");
  return link && id ? <Link className="font-medium text-brand hover:underline" to={`/suppliers/${id}`}>{name}</Link> : <>{name}</>;
}

export function ProductName({ id, sku = true }: { id: string | null | undefined; sku?: boolean }) {
  const product = useProduct(id);
  if (!product.data) return <>{product.isError ? "—" : "…"}</>;
  return <><span className="font-medium">{product.data.name}</span>{sku && <span className="ml-1.5 font-mono text-xs text-muted">{product.data.sku}</span>}</>;
}
