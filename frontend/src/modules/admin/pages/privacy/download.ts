import { ApiError, errorMessage } from "@/sdk";

/**
 * Save a file the API returned. The API needs the bearer token, so a plain link cannot be used: the request goes
 * through the typed client with `parseAs: "blob"` and the browser is handed the result.
 */
export async function saveDownload(request: Promise<{ data?: unknown; error?: unknown; response: Response }>, fileName: string): Promise<void> {
  const { data, error, response } = await request;
  if (!response.ok) throw new ApiError(errorMessage(readMessage(error), response.status), response.status);
  const blob = data instanceof Blob ? data : new Blob([JSON.stringify(data ?? {}, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** With parseAs "blob" the client leaves an error body as text: read the API's { message } out of it. */
function readMessage(error: unknown): unknown {
  if (typeof error !== "string") return error;
  try { return JSON.parse(error); } catch { return undefined; }
}
