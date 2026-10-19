import { api, errorMessage } from "@/sdk";

/** One Server-Sent Event: its name and its JSON data. */
export interface StreamEvent {
  event: string;
  data: Record<string, unknown>;
}

/**
 * Read Server-Sent Events from a byte stream. Handles events split across chunks, \r\n line ends, comment lines (": keep-alive") and
 * several `data:` lines. An event whose data is not JSON is skipped. Ends when the stream ends.
 */
export async function* parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<StreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const flush = (block: string): StreamEvent | null => {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith(":")) continue;
      const at = line.indexOf(":");
      const field = at < 0 ? line : line.slice(0, at);
      const value = at < 0 ? "" : line.slice(at + 1).replace(/^ /, "");
      if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (data.length === 0) return null;
    try {
      const parsed: unknown = JSON.parse(data.join("\n"));
      return parsed && typeof parsed === "object" ? { event, data: parsed as Record<string, unknown> } : null;
    } catch { return null; }
  };
  try {
    for (;;) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n?/g, "\n");
      let end = buffer.indexOf("\n\n");
      while (end >= 0) {
        const event = flush(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
        if (event) yield event;
        end = buffer.indexOf("\n\n");
      }
      if (done) break;
    }
    const rest = buffer.trim() ? flush(buffer) : null;
    if (rest) yield rest;
  } finally {
    reader.cancel().catch(() => undefined);
  }
}

export interface AskRequest {
  question: string;
  company_id?: string;
  session_id?: string;
  language: "en" | "sw";
}

/**
 * Ask Ziira as a chat: the events of one question (`status`, `text`, `sources`, `done`, or `error`), read from the streaming endpoint.
 * A refusal before the stream starts (not signed in, not allowed) arrives as an `error` event too. Aborting the signal stops the question.
 */
export async function* askStream(request: AskRequest, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
  const { response, error } = await api.POST("/api/v1/intel/ask/stream", { body: request, parseAs: "stream", signal });
  if (!response.ok || !response.body) {
    yield { event: "error", data: { reason: "failed", message: errorMessage(error, response.status) } };
    return;
  }
  yield* parseSse(response.body);
}
