import { Download } from "lucide-react";
import type { ReactNode } from "react";

import { ApiError, Button, errorMessage, toast, useMutation } from "@/sdk";

type Request = Promise<{ data?: unknown; error?: unknown; response: Response }>;

/** Save a file the API returned (it needs the sign-in token, so a plain link cannot be used). */
export async function saveFile(request: Request, fallbackName: string): Promise<void> {
  const { data, error, response } = await request;
  if (!response.ok) {
    let body = error;
    if (typeof body === "string") {
      try { body = JSON.parse(body); } catch { body = undefined; }
    }
    throw new ApiError(errorMessage(body, response.status), response.status);
  }
  const blob = data instanceof Blob ? data : new Blob([String(data ?? "")], { type: "text/csv" });
  const name = /filename="?([^";]+)"?/i.exec(response.headers.get("content-disposition") ?? "")?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** A button that downloads a file with the person's sign-in. */
export function DownloadButton({ children, request, fileName }: { children: ReactNode; request: () => Request; fileName: string }) {
  const save = useMutation({ meta: { silent: true }, onError: (e) => toast((e as Error).message, "bad"), mutationFn: () => saveFile(request(), fileName) });
  return <Button variant="secondary" loading={save.isPending} onClick={() => save.mutate()}><Download className="h-4 w-4" />{children}</Button>;
}
