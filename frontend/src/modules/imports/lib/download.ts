import { ApiError, errorMessage } from "@/sdk";

/** Save a file the API returned (a template, the rejected rows). The API needs the sign-in token, so a plain link cannot be used. */
export async function saveDownload(request: Promise<{ data?: unknown; error?: unknown; response: Response }>, fallbackName: string): Promise<void> {
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
