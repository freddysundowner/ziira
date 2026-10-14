import { Download } from "lucide-react";
import { type ReactNode } from "react";

import { Button, toast, useMutation } from "@/sdk";

import { saveDownload } from "../lib/download";

type Request = Promise<{ data?: unknown; error?: unknown; response: Response }>;

/** A button that fetches a file with the user's sign-in (the API needs the token) and saves it. */
export function DownloadButton({ children, request, fileName, variant = "secondary", size = "md" }: {
  children: ReactNode; request: () => Request; fileName: string; variant?: "primary" | "secondary" | "ghost"; size?: "sm" | "md";
}) {
  const download = useMutation({ mutationFn: () => saveDownload(request(), fileName), onError: (e) => toast((e as Error).message, "bad"), meta: { silent: true } });
  return <Button variant={variant} size={size} loading={download.isPending} onClick={() => download.mutate()}><Download className="h-4 w-4" />{children}</Button>;
}
