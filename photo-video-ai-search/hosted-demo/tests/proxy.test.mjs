import test from "node:test";
import assert from "node:assert/strict";
import { createHandler, managedURL, embeddingBody, EMBEDDING_MODEL, GENERATION_MODEL } from "../worker/index.js";

const embedding = "https://port8000-fixture.tunnel.applications.eu-north1.nebius.cloud";
const generation = "https://port8001-fixture.tunnel.applications.eu-north1.nebius.cloud";
const token = "fixture-only-never-a-real-token";
const vector = () => Array.from({ length: 4096 }, (_, i) => i === 0 ? 2 : 0);
const response = value => new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } });
const png = "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAEklEQVR4nO3BAQ0AAADCoPdPbQ43oAAAAAAAAAAAfg0AAgABYvR0AAAAAElFTkSuQmCC";

function request(path, body, changes = {}) {
  return new Request("https://demo.example" + path, { method: "POST", headers: { "Content-Type": "application/json", Origin: "https://demo.example", ...changes.headers }, body: JSON.stringify(body), ...Object.fromEntries(Object.entries(changes).filter(([key]) => key !== "headers")) });
}

function upstream(calls = [], changes = {}) {
  return async (url, options) => {
    calls.push({ url, options });
    assert.equal(options.redirect, "manual");
    assert.equal(options.headers.Authorization, "Bearer " + token);
    if (url.endsWith("/v1/models")) return response({ data: [{ id: url.startsWith(embedding) ? EMBEDDING_MODEL : GENERATION_MODEL }] });
    if (url.endsWith("/v1/embeddings")) return response({ data: [{ embedding: changes.vector || vector() }] });
    if (url.endsWith("/v1/images/generations")) {
      if (changes.wait) await changes.wait;
      return response({ data: [{ b64_json: png }] });
    }
    throw new Error("Unexpected fixture URL");
  };
}

test("connection verifies both model ports and a real-shaped 4096-vector probe", async () => {
  const calls = [];
  const app = createHandler({ fetchImpl: upstream(calls) });
  const res = await app.fetch(request("/api/connect", { embedding_url: embedding, generation_url: generation, token }));
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { embedding_model: EMBEDDING_MODEL, generation_model: GENERATION_MODEL, dimensions: 4096 });
  assert.equal(calls.length, 3);
  const body = JSON.parse(calls.find(item => item.url.endsWith("/v1/embeddings")).options.body);
  assert.deepEqual(body, embeddingBody([{ type: "text", text: "Connection check" }]));
  assert.equal(res.headers.get("cache-control"), "no-store");
});

test("first-stage search connection verifies embeddings before creation setup", async () => {
  const calls = [];
  const res = await createHandler({ fetchImpl: upstream(calls) }).fetch(request("/api/connect", { embedding_url: embedding, token }));
  assert.equal(res.status, 200);
  assert.equal((await res.json()).generation_model, null);
  assert.equal(calls.length, 2);
});

test("adding generation checks only FLUX and never re-embeds or generates", async () => {
  const calls = [];
  const res = await createHandler({ fetchImpl: upstream(calls) }).fetch(request("/api/connect-generation", { generation_url: generation + "/", token }));
  assert.equal(res.status, 200);
  const payload = await res.json();
  assert.deepEqual(payload, { generation_url: generation, generation_model: GENERATION_MODEL });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, generation + "/v1/models");
  assert.equal(calls[0].options.method, "GET");
  assert.equal(res.headers.get("cache-control"), "no-store");
  assert(!JSON.stringify(payload).includes(token));
});

test("generation-only connection rejects invalid destinations, credentials and models", async t => {
  for (const url of [embedding, generation + "/v1", "http://127.0.0.1:8001", "https://example.com"]) {
    await t.test("invalid generation URL: " + url, async () => {
      const calls = [];
      const res = await createHandler({ fetchImpl: upstream(calls) }).fetch(request("/api/connect-generation", { generation_url: url, token }));
      assert.equal(res.status, 422);
      assert.equal(calls.length, 0);
    });
  }
  for (const item of [
    { name: "wrong model", fn: async () => response({ data: [{ id: EMBEDDING_MODEL }] }), status: 422 },
    { name: "wrong token", fn: async () => new Response("private " + token, { status: 401 }), status: 401 },
    { name: "redirect", fn: async () => new Response(null, { status: 302, headers: { Location: "http://127.0.0.1" } }), status: 422 },
  ]) await t.test(item.name, async () => {
    const res = await createHandler({ fetchImpl: item.fn }).fetch(request("/api/connect-generation", { generation_url: generation, token }));
    assert.equal(res.status, item.status);
    assert(!(await res.text()).includes(token));
  });
});

test("SSRF, credentials, extra paths, redirects and wrong ports are rejected", async t => {
  for (const url of ["http://127.0.0.1:6333", "https://example.com", embedding + "/v1", embedding + "?token=secret", embedding + "#secret", embedding.replace("https://", "https://user:password@"), embedding.replace(".nebius.cloud", ".nebius.cloud.evil.example"), generation, embedding.replace("https://", "http://"), embedding + ":4431"]) {
    await t.test(url.split("?")[0], async () => {
      let called = false;
      const res = await createHandler({ fetchImpl: async () => { called = true; } }).fetch(request("/api/connect", { embedding_url: url, token }));
      assert.equal(res.status, 422);
      assert.equal(called, false);
      assert.ok(!(await res.text()).includes(token));
    });
  }
  const redirect = createHandler({ fetchImpl: async () => new Response(null, { status: 302, headers: { Location: "http://127.0.0.1" } }) });
  assert.equal((await redirect.fetch(request("/api/connect", { embedding_url: embedding, token }))).status, 422);
  assert.equal(managedURL(embedding + "/", 8000), embedding);
});

test("wrong models, dimensions, zero vectors and auth failures cannot connect", async t => {
  for (const item of [
    { name: "wrong model", fn: async () => response({ data: [{ id: "a-different-model" }] }), status: 422 },
    { name: "wrong dimensions", fn: upstream([], { vector: [1, 2, 3] }), status: 422 },
    { name: "zero vector", fn: upstream([], { vector: Array(4096).fill(0) }), status: 422 },
    { name: "auth error", fn: async () => new Response("sensitive upstream body " + token, { status: 401 }), status: 401 },
    { name: "unavailable", fn: async () => { throw new Error("sensitive upstream " + token); }, status: 503 },
  ]) await t.test(item.name, async () => {
    const res = await createHandler({ fetchImpl: item.fn }).fetch(request("/api/connect", { embedding_url: embedding, token }));
    assert.equal(res.status, item.status);
    assert.ok(!(await res.text()).includes(token));
  });
});

test("embedding relays only fixed Qwen protocol, base64 media and normalized vector", async () => {
  const calls = [];
  const app = createHandler({ fetchImpl: upstream(calls) });
  const res = await app.fetch(request("/api/embed", { base_url: embedding, token, kind: "text", text: "coffee", model: "cannot-override" }));
  assert.equal(res.status, 200);
  assert.deepEqual((await res.json()).vector, Array.from({ length: 4096 }, (_, i) => i === 0 ? 1 : 0));
  const body = JSON.parse(calls[0].options.body);
  assert.equal(body.model, EMBEDDING_MODEL);
  assert.equal(body.messages[1].content[0].text, "coffee");
  assert.equal(body.continue_final_message, true);
  const media = await app.fetch(request("/api/embed", { base_url: embedding, token, kind: "image", image_data_url: "data:image/jpeg;base64,YWJj" }));
  assert.equal(media.status, 200);
  assert.equal(JSON.parse(calls[1].options.body).messages[1].content[0].type, "image_url");
  for (const value of ["https://private.example/image", "data:image/svg+xml;base64,YWJj", "data:image/jpeg;base64,###"]) {
    assert.equal((await app.fetch(request("/api/embed", { base_url: embedding, token, kind: "image", image_data_url: value }))).status, 422);
  }
});

test("generation requires approval, dedupes in-flight, does not persist image responses", async () => {
  const calls = [];
  let release;
  const wait = new Promise(resolve => { release = resolve; });
  const app = createHandler({ fetchImpl: upstream(calls, { wait }) });
  const body = { base_url: generation, token, prompt: "A jade dragon teapot", approved: true, request_id: "c8578ace-ec9b-48f6-aac8-558fb969aaab" };
  assert.equal((await app.fetch(request("/api/generate", { ...body, approved: false }))).status, 422);
  const first = app.fetch(request("/api/generate", body));
  const duplicate = app.fetch(request("/api/generate", body));
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(calls.length, 1);
  release();
  const results = await Promise.all([first, duplicate]);
  for (const res of results) {
    assert.equal(res.status, 200);
    assert.equal((await res.json()).image_data_url, "data:image/png;base64," + png);
  }
  assert.equal((await app.fetch(request("/api/generate", body))).status, 409);
  assert.equal(calls.length, 1);
});

test("only explicit FLUX content-check refusals are described as model declines", async t => {
  const refusalBodies = [
    { detail: "This request or its output was declined by the model's content checks." },
    { detail: "The model declined the request or its output. Try a different description." },
    { code: "model_declined", detail: "private prompt " + token },
    { error: { code: "model_declined", message: "private prompt " + token } },
    { detail: { code: "model_declined", message: "private prompt " + token } },
  ];
  for (const status of [400, 422]) for (const [index, upstreamBody] of refusalBodies.entries()) {
    await t.test(`explicit refusal ${status}/${index}`, async () => {
      let calls = 0;
      const app = createHandler({ fetchImpl: async () => {
        calls++;
        return new Response(JSON.stringify(upstreamBody), { status, headers: { "Content-Type": "application/json" } });
      } });
      const result = await app.fetch(request("/api/generate", { base_url: generation, token,
        prompt: "A plain ceramic cup", approved: true, request_id: crypto.randomUUID() }));
      assert.equal(result.status, 422);
      const body = await result.json();
      assert.equal(body.code, "model_declined");
      assert.match(body.detail, /FLUX’s content checks/);
      assert(!JSON.stringify(body).includes(token));
      assert(!JSON.stringify(body).includes("private prompt"));
      assert.equal(calls, 1, "A refusal must not be retried automatically.");
    });
  }
});

test("unknown 400/422 responses are request errors without inventing a refusal or exposing upstream content", async t => {
  const privatePrompt = "private test prompt about a ceramic cup";
  const changes = [
    { label: "unknown detail", value: { detail: privatePrompt + token } },
    { label: "schema validation", value: { detail: [{ type: "literal_error", input: privatePrompt + token }] } },
    { label: "unknown code", value: { code: "invalid_argument", message: privatePrompt + token } },
    { label: "refusal-like substring", value: { detail: "This request or its output was declined by the model's content checks. " + token } },
    { label: "null JSON", value: null },
    { label: "array JSON", value: [{ code: "model_declined" }] },
  ];
  for (const status of [400, 422]) for (const change of changes) await t.test(`${status}: ${change.label}`, async () => {
    let calls = 0;
    const app = createHandler({ fetchImpl: async () => {
      calls++;
      return new Response(JSON.stringify(change.value), { status, headers: { "Content-Type": "application/json" } });
    } });
    const result = await app.fetch(request("/api/generate", { base_url: generation, token,
      prompt: privatePrompt, approved: true, request_id: crypto.randomUUID() }));
    assert.equal(result.status, 422);
    const body = await result.json();
    assert.equal(body.code, "model_request_invalid");
    assert.match(body.detail, /request format or settings/);
    assert(!JSON.stringify(body).includes(token));
    assert(!JSON.stringify(body).includes(privatePrompt));
    assert(!/declin|unavailable/i.test(body.detail));
    assert.equal(calls, 1);
  });
});

test("refusal diagnostics preserve only allowlisted stages and categories", async t => {
  for (const [stage, category] of [["prompt", "copyright_or_public_figure"], ["output", "adult_content"], [token, token]]) {
    await t.test(stage === token ? "unrecognized diagnostics" : stage, async () => {
      const app = createHandler({ fetchImpl: async () => Response.json({
        detail: { code: "model_declined", stage, category, message: "private " + token },
      }, { status: 400 }) });
      const result = await app.fetch(request("/api/generate", { base_url: generation, token,
        prompt: "A plain ceramic cup", approved: true, request_id: crypto.randomUUID() }));
      const body = await result.json();
      assert.equal(result.status, 422);
      assert.equal(body.stage, stage === token ? "unknown" : stage);
      assert.equal(body.category, category === token ? "unknown" : category);
      assert(!JSON.stringify(body).includes(token));
      if (stage === "prompt") assert.match(body.detail, /prompt check/);
      if (stage === "output") assert.match(body.detail, /created an image/);
    });
  }
});

test("malformed, oversized and interrupted error bodies are bounded and never reflected", async t => {
  const sensitive = "private prompt " + token;
  const bodies = [
    { label: "invalid JSON", make: () => new Response("{broken " + sensitive, { status: 400, headers: { "Content-Type": "application/json" } }) },
    { label: "non-JSON", make: () => new Response(sensitive, { status: 400, headers: { "Content-Type": "text/html" } }) },
    { label: "missing content type", make: () => new Response(JSON.stringify({ code: "model_declined" }), { status: 400 }) },
    { label: "declared oversize", make: () => new Response(JSON.stringify({ code: "model_declined", detail: sensitive }), { status: 400, headers: { "Content-Type": "application/json", "Content-Length": String(16 * 1024 + 1) } }) },
    { label: "streamed oversize", make: () => new Response(JSON.stringify({ code: "model_declined", detail: sensitive.repeat(1024) }), { status: 400, headers: { "Content-Type": "application/json" } }) },
    { label: "broken stream", make: () => new Response(new ReadableStream({ start(controller) { controller.error(new Error(sensitive)); } }), { status: 422, headers: { "Content-Type": "application/json" } }) },
  ];
  for (const body of bodies) await t.test(body.label, async () => {
    const app = createHandler({ fetchImpl: async () => body.make() });
    const result = await app.fetch(request("/api/generate", { base_url: generation, token,
      prompt: "A plain ceramic cup", approved: true, request_id: crypto.randomUUID() }));
    assert.equal(result.status, 422);
    const payload = await result.json();
    assert.equal(payload.code, "model_request_invalid");
    assert(!JSON.stringify(payload).includes(token));
    assert(!JSON.stringify(payload).includes("private prompt"));
  });
});

test("embedding and model-list validation failures cannot be mistaken for FLUX refusal", async () => {
  const app = createHandler({ fetchImpl: async () => new Response(JSON.stringify({ code: "model_declined" }), {
    status: 400, headers: { "Content-Type": "application/json" },
  }) });
  for (const [path, body] of [
    ["/api/embed", { base_url: embedding, token, kind: "text", text: "coffee" }],
    ["/api/connect-generation", { generation_url: generation, token }],
  ]) {
    const result = await app.fetch(request(path, body));
    assert.equal(result.status, 422);
    assert.equal((await result.json()).code, "model_request_invalid");
  }
});

test("no ambient owner credentials, cross-site calls, arbitrary paths or private files", async () => {
  let called = false;
  const app = createHandler({ assets: { "/index.html": { type: "text/html", body: btoa("real app shell") } }, fetchImpl: async () => { called = true; } });
  assert.equal((await app.fetch(request("/api/connect", { embedding_url: embedding }))).status, 422);
  assert.equal((await app.fetch(request("/api/connect", { embedding_url: embedding, token }, { headers: { Origin: "https://another.example" } }))).status, 403);
  assert.equal((await app.fetch(request("/api/proxy", { base_url: "http://localhost", token }))).status, 404);
  assert.equal((await app.fetch(new Request("https://demo.example/.env"))).status, 404);
  assert.equal((await app.fetch(new Request("https://demo.example/worker/index.js"))).status, 404);
  const page = await app.fetch(new Request("https://demo.example/"));
  assert.equal(page.status, 200);
  assert.equal(await page.text(), "real app shell");
  assert.equal(called, false);
});

test("payload size and JSON bounds are enforced before upstream calls", async () => {
  const app = createHandler({ fetchImpl: async () => { throw new Error("must not call"); } });
  const large = request("/api/embed", { text: "a".repeat(3 * 1024 * 1024) });
  assert.equal((await app.fetch(large)).status, 413);
  assert.equal((await app.fetch(new Request("https://demo.example/api/embed", { method: "POST", body: "{}" }))).status, 415);
  assert.equal((await app.fetch(new Request("https://demo.example/api/embed", { method: "POST", headers: { "Content-Type": "application/json" }, body: "not json" }))).status, 422);
});
