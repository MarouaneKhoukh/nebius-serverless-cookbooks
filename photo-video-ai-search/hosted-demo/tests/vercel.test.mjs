import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { createVercelHandler } from "../api/[...path].mjs";
import { EMBEDDING_MODEL } from "../worker/index.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const embedding = "https://port8000-fixture.tunnel.applications.eu-north1.nebius.cloud";
const generation = "https://port8001-fixture.tunnel.applications.eu-north1.nebius.cloud";
const token = "fixture-only-not-a-real-token";
function request(path = "/api/connect", body = { embedding_url: embedding, token }, headers = {}) {
  return new Request("https://demo.vercel.app" + path, { method: "POST", headers: {
    "Content-Type": "application/json", Origin: "https://demo.vercel.app", "x-real-ip": "192.0.2.1", ...headers,
  }, body: JSON.stringify(body) });
}
function upstream(calls) {
  return async (url, options) => {
    calls.push({ url, options });
    assert.equal(options.redirect, "manual");
    assert.equal(options.headers.Authorization, "Bearer " + token);
    return Response.json(url.endsWith("/v1/models") ? { data: [{ id: EMBEDDING_MODEL }] }
      : { data: [{ embedding: Array.from({ length: 4096 }, (_, i) => i === 0 ? 1 : 0) }] });
  };
}

test("Vercel relay accepts BYO requests and exposes a no-inference health check", async () => {
  const calls = [];
  const app = createVercelHandler({ fetchImpl: upstream(calls) });
  const health = await app.fetch(new Request("https://demo.vercel.app/api/health"));
  assert.equal(health.status, 200);
  assert.deepEqual(await health.json(), { ok: true });
  assert.equal(calls.length, 0);
  const connected = await app.fetch(request());
  assert.equal(connected.status, 200);
  assert.equal((await connected.json()).dimensions, 4096);
  assert.equal(connected.headers.get("cache-control"), "no-store");
  assert.equal(calls.length, 2);
  assert(calls.every(call => call.url.startsWith(embedding + "/v1/")));
});

test("Vercel relay keeps SSRF, credential and cross-origin restrictions", async () => {
  const calls = [];
  const app = createVercelHandler({ fetchImpl: upstream(calls) });
  for (const [body, headers, status] of [
    [{ embedding_url: "http://127.0.0.1:8000", token }, {}, 422],
    [{ embedding_url: embedding }, {}, 422],
    [{ embedding_url: embedding, token }, { Origin: "https://another.example" }, 403],
    [{ embedding_url: embedding, token }, { "Sec-Fetch-Site": "cross-site" }, 403],
  ]) {
    const result = await app.fetch(request("/api/connect", body, headers));
    assert.equal(result.status, status);
    assert(!(await result.text()).includes(token));
  }
  assert.equal(calls.length, 0);
});

test("Vercel IP rate limit cannot be bypassed by a forged Cloudflare IP", async () => {
  const calls = [];
  const app = createVercelHandler({ fetchImpl: upstream(calls), now: () => 60_000 });
  for (let i = 0; i < 90; i++) {
    const result = await app.fetch(request("/api/connect", undefined, { "CF-Connecting-IP": "forged-" + i }));
    assert.equal(result.status, 200);
  }
  assert.equal((await app.fetch(request("/api/connect", undefined, { "CF-Connecting-IP": "new-forged-value" }))).status, 429);
  assert.equal(calls.length, 180);
  assert.equal((await app.fetch(request("/api/connect", undefined, { "x-real-ip": "192.0.2.2" }))).status, 200);
});

test("Vercel bounds upstream generation below its response ceiling without leaking credentials", async () => {
  const app = createVercelHandler({ fetchImpl: async () => new Response("{}", {
    headers: { "Content-Type": "application/json", "Content-Length": "4000001" },
  }) });
  const result = await app.fetch(request("/api/generate", { base_url: generation, token,
    prompt: "A teal ceramic teapot", approved: true, request_id: "c8578ace-ec9b-48f6-aac8-558fb969aaab" }));
  assert.equal(result.status, 413);
  assert.equal((await result.json()).code, "response_too_large");
});

test("Vercel build publishes public assets only, with correct function wiring", async () => {
  const built = spawnSync(process.execPath, ["scripts/build-static.mjs"], { cwd: root, encoding: "utf8" });
  assert.equal(built.status, 0, built.stderr);
  const files = await readdir(new URL("../dist/", import.meta.url), { recursive: true });
  for (const name of ["index.html", "app.js", "styles.css", "retrieval.js", "brand/nebius-logo.svg", "examples/coffee-beans.jpg"]) {
    assert(files.includes(name), name + " is published");
  }
  assert(!files.some(name => /(?:^|\/)(?:server|worker|api|tests|\.env|\.vercel)(?:\/|\.|$)/.test(name)));
  const config = JSON.parse(await readFile(new URL("../vercel.json", import.meta.url), "utf8"));
  assert.equal(config.outputDirectory, "dist");
  assert.equal(config.functions["api/**/*.mjs"].maxDuration, 300);
  assert(config.headers[0].headers.some(item => item.key === "Content-Security-Policy" && item.value.includes("connect-src 'self'")));
  const page = await readFile(new URL("../dist/index.html", import.meta.url), "utf8");
  assert(page.includes("Powered by Nebius Serverless AI"));
  assert(!page.includes(token));
});
