import { ApiError, errorMessage } from "@/sdk";

/**
 * Save a file the API returned. The API needs the bearer token, so a plain link cannot be used: the request goes through
 * the typed client with `parseAs: "blob"` and the browser is handed the result.
 */
export async function saveDownload(request: Promise<{ data?: unknown; error?: unknown; response: Response }>, fallbackName: string): Promise<void> {
  const { data, error, response } = await request;
  if (!response.ok) throw new ApiError(errorMessage(parsed(error), response.status), response.status);
  const blob = data instanceof Blob ? data : new Blob([String(data ?? "")], { type: "text/csv" });
  const name = filenameFrom(response.headers.get("content-disposition")) ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** With parseAs "blob" the client leaves an error body as text: read the API's { message } out of it. */
function parsed(error: unknown): unknown {
  if (typeof error !== "string") return error;
  try { return JSON.parse(error); } catch { return undefined; }
}

export function filenameFrom(disposition: string | null): string | null {
  const match = /filename="?([^";]+)"?/i.exec(disposition ?? "");
  return match?.[1] ?? null;
}
