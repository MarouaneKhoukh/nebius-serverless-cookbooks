/** Vercel Node adapter. Visitors supply all GPU URLs and credentials per request. */
import { createHandler } from "../worker/index.js";

export function createVercelHandler(options = {}) {
  const relay = createHandler({
    ...options,
    // Vercel overwrites these headers at its edge. Never trust a visitor's
    // CF-Connecting-IP on this host. This is a best-effort, per-instance limit.
    clientIdentity: request => request.headers.get("x-vercel-forwarded-for")
      || request.headers.get("x-real-ip") || request.headers.get("x-forwarded-for") || "unknown",
    // Leave headroom below Vercel's 4.5 MB response limit, including base64/JSON.
    maxGenerationResponse: 4_000_000,
    maxGeneratedPNG: 2_900_000,
  });
  return { fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/api/health" && request.method === "GET") {
      url.pathname = "/health";
      return relay.fetch(new Request(url, request));
    }
    return relay.fetch(request);
  } };
}

export default createVercelHandler();
