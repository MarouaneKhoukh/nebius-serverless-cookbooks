/** Local preview of the exact stateless Worker. No browser credentials are logged. */
import { createServer } from "node:http";
import { createHandler } from "./worker/index.js";
import { assets } from "./scripts/build.mjs";
const port = Number(process.env.PORT || 8085);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Set PORT to a valid local port.");
const server = createServer(async (incoming, outgoing) => {
  try {
    const chunks = [];
    let size = 0;
    for await (const chunk of incoming) {
      size += chunk.length;
      if (size > 3 * 1024 * 1024) {
        outgoing.writeHead(413, { "Content-Type": "application/json", "Cache-Control": "no-store" });
        outgoing.end(JSON.stringify({ detail: "The request exceeds this demo’s size limit." }));
        return;
      }
      chunks.push(chunk);
    }
    const body = Buffer.concat(chunks);
    const host = incoming.headers.host;
    if (!["127.0.0.1:" + port, "localhost:" + port].includes(host)) {
      outgoing.writeHead(400, { "Content-Type": "application/json" });
      outgoing.end(JSON.stringify({ detail: "Open this demo using its printed local address." }));
      return;
    }
    const request = new Request(`http://${host}${incoming.url}`, { method: incoming.method, headers: incoming.headers,
      ...(["GET", "HEAD"].includes(incoming.method) ? {} : { body }) });
    const response = await handler.fetch(request);
    outgoing.writeHead(response.status, Object.fromEntries(response.headers));
    outgoing.end(Buffer.from(await response.arrayBuffer()));
  } catch {
    outgoing.writeHead(500, { "Content-Type": "application/json", "Cache-Control": "no-store" });
    outgoing.end(JSON.stringify({ detail: "The local server could not complete this request." }));
  }
});
const handler = createHandler({ assets: await assets() });
server.requestTimeout = 300000;
server.on("error", error => {
  console.error(error.code === "EADDRINUSE" ? `Port ${port} is already in use. Close the earlier preview or choose another PORT.` : "The local demo server could not start.");
  process.exitCode = 1;
});
server.listen(port, "127.0.0.1", () => console.log(`Nebius Image Search: http://127.0.0.1:${port}/`));
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => server.close(() => process.exit(0)));
