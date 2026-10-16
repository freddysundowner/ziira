// A tiny static file server for the built site (used by the a11y check and Lighthouse). Mirrors how a plain static host behaves:
// directory URLs serve index.html, a missing path serves 404.html with status 404.
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const TYPES = {
  ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".json": "application/json", ".xml": "application/xml",
  ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".avif": "image/avif", ".txt": "text/plain; charset=utf-8",
  ".webmanifest": "application/manifest+json", ".ico": "image/x-icon",
};

export function serve(dist, port = 0) {
  const root = path.resolve(dist);
  const server = http.createServer((req, res) => {
    const url = new URL(req.url ?? "/", "http://x");
    let file = path.join(root, decodeURIComponent(url.pathname));
    if (!file.startsWith(root)) { res.writeHead(403).end(); return; }
    if (fs.existsSync(file) && fs.statSync(file).isDirectory()) {
      if (!url.pathname.endsWith("/")) { res.writeHead(301, { Location: url.pathname + "/" }).end(); return; }
      file = path.join(file, "index.html");
    }
    let status = 200;
    if (!fs.existsSync(file)) { file = path.join(root, "404.html"); status = 404; }
    res.writeHead(status, { "Content-Type": TYPES[path.extname(file)] ?? "application/octet-stream", "Cache-Control": "no-cache" });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve({ server, port: server.address().port, close: () => server.close() })));
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const { port } = await serve(process.argv[2] ?? "dist", Number(process.argv[3] ?? 4321));
  console.log(`serving on http://127.0.0.1:${port}`);
}
