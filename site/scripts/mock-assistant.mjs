// A small local stand-in for the Ziira assistant API, to develop and test the floating "Ask Ziira" without the backend.
//   node scripts/mock-assistant.mjs [port]            (default 8099)
//   PUBLIC_ASSISTANT_API_URL=http://localhost:8099 npm run build && npm run preview     (the site then talks to this mock)
// Contract (docs/marketing-site.md "Floating Ask Ziira"): GET /api/v1/public/assistant/config, POST /api/v1/public/assistant/stream (SSE).
// Canned replies only (never real information). Type a word to try a path: "price", "error", "busy", "off", "long", "cut", or anything else.
import http from "node:http";

const port = Number(process.argv[2] || process.env.PORT || 8099);
const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type, Accept", "Access-Control-Allow-Methods": "GET, POST, OPTIONS" };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const send = (res, name, data) => res.write(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`);

const server = http.createServer(async (req, res) => {
  if (req.method === "OPTIONS") { res.writeHead(204, cors); return res.end(); }
  if (req.url === "/api/v1/public/assistant/config") {
    res.writeHead(200, { ...cors, "Content-Type": "application/json" });
    return res.end(JSON.stringify({ enabled: process.env.MOCK_OFF ? false : true, greeting: "Hi, I am Ziira. Ask me about plans, what Ziira does, or whether it fits your business.", suggestions: ["What does Ziira cost?", "Is Ziira right for a garage?", "How do the daily checks work?", "Can it work with Odoo?"] }));
  }
  if (req.url === "/api/v1/public/assistant/stream" && req.method === "POST") {
    let body = ""; for await (const c of req) body += c;
    const { message = "", history = [] } = JSON.parse(body || "{}");
    const m = message.toLowerCase();
    res.writeHead(200, { ...cors, "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
    if (m.includes("off")) { send(res, "error", { reason: "off", message: "Ask Ziira is switched off right now." }); return res.end(); }
    if (m.includes("busy")) { send(res, "error", { reason: "busy", message: "Ask Ziira is busy. Please try again in a moment.", retry_after: 5 }); return res.end(); }
    send(res, "status", { text: "Looking at our pricing…" }); await sleep(900);
    if (m.includes("error")) { send(res, "error", { reason: "provider_failed", message: "Ask Ziira could not answer just now." }); return res.end(); }
    send(res, "status", { text: "Reading the plans page…" }); await sleep(700);
    const lines = m.includes("long")
      ? ["This is a longer answer so you can see the typing and the scrolling.", "- Ziira runs sales, stock, buying, accounting and payroll in one system.", "- It checks the business every day and tells you what needs you.", "- Anything it suggests waits for you to approve.", "Open the pages below for the details."]
      : [`This is a canned reply from the mock server (it is not real information). You said: "${message.slice(0, 80)}".`, `You have sent ${history.length} earlier messages in this chat.`, "The real assistant answers from the pages of this site."];
    for (const l of lines) { send(res, "text", { text: l }); await sleep(450); }
    if (m.includes("cut")) { return res.destroy(); }
    send(res, "links", { items: [{ title: "Pricing", href: "/pricing/" }, { title: "Garages and body shops", href: "/solutions/garages-and-body-shops/" }] });
    send(res, "done", {}); return res.end();
  }
  res.writeHead(404, cors); res.end();
});
server.listen(port, () => console.log(`mock assistant API on http://localhost:${port}  (MOCK_OFF=1 makes config say disabled)`));
