import { describe, expect, it } from "vitest";

import { parseSse, type StreamEvent } from "./sse";

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}
async function collect(body: ReadableStream<Uint8Array>): Promise<StreamEvent[]> {
  const out: StreamEvent[] = [];
  for await (const e of parseSse(body)) out.push(e);
  return out;
}

describe("parseSse", () => {
  it("reads events in order", async () => {
    const events = await collect(streamOf('event: status\ndata: {"text":"Looking"}\n\nevent: text\ndata: {"text":"Hi. "}\n\n'));
    expect(events).toEqual([{ event: "status", data: { text: "Looking" } }, { event: "text", data: { text: "Hi. " } }]);
  });
  it("puts together an event that arrives in pieces, even in the middle of a word or a character", async () => {
    const events = await collect(streamOf('event: te', 'xt\ndata: {"text":"Mauz', 'o 116"}\n', "\nevent: done\ndata: {}\n\n"));
    expect(events.map((e) => e.event)).toEqual(["text", "done"]);
    expect(events[0]?.data.text).toBe("Mauzo 116");
    const bytes = new TextEncoder().encode('event: text\ndata: {"text":"é"}\n\n');
    const split = new ReadableStream<Uint8Array>({ start(c) { c.enqueue(bytes.slice(0, 27)); c.enqueue(bytes.slice(27)); c.close(); } });
    expect((await collect(split))[0]?.data.text).toBe("é");
  });
  it("accepts \\r\\n line ends, comments, and an unfinished last event", async () => {
    const events = await collect(streamOf(': keep-alive\r\n\r\nevent: text\r\ndata: {"text":"a"}\r\n\r\nevent: done\ndata: {"x":1}'));
    expect(events.map((e) => e.event)).toEqual(["text", "done"]);
  });
  it("skips an event whose data is not JSON and joins several data lines", async () => {
    const events = await collect(streamOf('event: text\ndata: nope\n\nevent: text\ndata: {"text":\ndata: "x"}\n\n'));
    expect(events).toEqual([{ event: "text", data: { text: "x" } }]);
  });
});
