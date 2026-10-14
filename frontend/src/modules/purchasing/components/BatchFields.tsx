import { Field, Input, useTranslation } from "@/sdk";

import { useProduct } from "../hooks";

/** Batch number and expiry, shown only for products that are tracked by batch. */
export function BatchFields({ productId, batchNo, expiry, onBatch, onExpiry }: {
  productId: string; batchNo: string; expiry: string; onBatch: (v: string) => void; onExpiry: (v: string) => void;
}) {
  const { t } = useTranslation("purchasing");
  const product = useProduct(productId || null);
  if (!product.data?.is_batch_tracked) return null;
  return (
    <>
      <Field label={t("batchNo")}><Input value={batchNo} onChange={(e) => onBatch(e.target.value)} maxLength={60} /></Field>
      <Field label={t("expiry")}><Input type="date" value={expiry} onChange={(e) => onExpiry(e.target.value)} /></Field>
    </>
  );
}
