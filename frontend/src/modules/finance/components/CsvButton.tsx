import { Download } from "lucide-react";

import { Button, useMutation, useTranslation } from "@/sdk";

import { downloadFile } from "../api";

/** Downloads a CSV from the API (with the sign-in token). A failure shows as a message, the button comes back. */
export function CsvButton({ request, fallbackName, label }: { request: () => Promise<{ data?: unknown; error?: unknown; response: Response }>; fallbackName: string; label?: string }) {
  const { t } = useTranslation("finance");
  const download = useMutation({ mutationFn: () => downloadFile(request(), fallbackName) });
  return (
    <Button variant="secondary" loading={download.isPending} onClick={() => download.mutate()}>
      <Download className="h-4 w-4" />{label ?? t("downloadCsv")}
    </Button>
  );
}
