import { Download } from "lucide-react";
import type { ReactNode } from "react";

import { ApiError, Button, errorMessage, toast, useMutation } from "@/sdk";

type Request = Promise<{ data?: unknown; error?: unknown; response: Response }>;

/** A button that fetches a file with the person's sign-in (a plain link cannot) and saves it. */
export function DownloadButton({ children, request, fileName }: { children: ReactNode; request: () => Request; fileName: string }) {
  const save = useMutation({
    meta: { silent: true },
    onError: (e) => toast((e as Error).message, "bad"),
    mutationFn: async () => {
      const { data, error, response } = await request();
      if (!response.ok) throw new ApiError(errorMessage(error, response.status), response.status);
      const blob = data instanceof Blob ? data : new Blob([String(data ?? "")], { type: "text/csv" });
      const name = /filename="?([^";]+)"?/i.exec(response.headers.get("content-disposition") ?? "")?.[1] ?? fileName;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    },
  });
  return <Button variant="secondary" loading={save.isPending} onClick={() => save.mutate()}><Download className="h-4 w-4" />{children}</Button>;
}
