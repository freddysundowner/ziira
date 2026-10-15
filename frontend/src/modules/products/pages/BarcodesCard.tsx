import { Pencil } from "lucide-react";
import { useState } from "react";

import { api, Alert, Badge, Button, Card, Field, Modal, Textarea, toast, unwrap, useCan, useMutation, useQueryClient, useTranslation } from "@/sdk";

/** The codes a scanner reads for this product. A code belongs to one product; the till finds the product by any of them. */
export function BarcodesCard({ productId, barcodes }: { productId: string; barcodes: string[] }) {
  const { t } = useTranslation("products");
  const canManage = useCan("products.manage");
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.PUT("/api/v1/products/products/{product_id}/barcodes", {
      params: { path: { product_id: productId } },
      body: { barcodes: text.split(/[\n,;]+/).map((c) => c.trim()).filter(Boolean) },
    })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["product", productId] });
      void qc.invalidateQueries({ queryKey: ["products"] });
      toast(t("barcodes.saved"), "ok");
      setEditing(false);
    },
  });

  const open = () => { setText(barcodes.join("\n")); save.reset(); setEditing(true); };
  return (
    <>
      <Card title={t("barcodes.title")} actions={canManage ? <Button variant="secondary" size="sm" onClick={open}><Pencil className="h-3.5 w-3.5" />{t("barcodes.edit")}</Button> : undefined}>
        {barcodes.length === 0 ? (
          <p className="text-sm text-muted">{t("barcodes.none")}</p>
        ) : (
          <ul className="flex flex-wrap gap-2" aria-label={t("barcodes.title")}>
            {barcodes.map((code) => <li key={code}><Badge className="font-mono">{code}</Badge></li>)}
          </ul>
        )}
      </Card>
      <Modal open={editing} onClose={() => (save.isPending ? undefined : setEditing(false))} title={t("barcodes.editTitle")}
        footer={<><Button variant="secondary" onClick={() => setEditing(false)} disabled={save.isPending}>{t("cancel")}</Button><Button loading={save.isPending} onClick={() => save.mutate()}>{t("barcodes.save")}</Button></>}>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <Field label={t("barcodes.codes")} hint={t("barcodes.hint")}>
            <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={5} spellCheck={false} autoFocus className="font-mono" />
          </Field>
          {save.error && <Alert tone="bad">{save.error.message}</Alert>}
        </form>
      </Modal>
    </>
  );
}
