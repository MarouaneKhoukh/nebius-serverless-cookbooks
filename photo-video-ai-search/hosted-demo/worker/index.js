/** Stateless, same-origin Nebius relay. No credentials or visitor media are persisted. */
export const EMBEDDING_MODEL = "Qwen/Qwen3-VL-Embedding-8B";
export const GENERATION_MODEL = "black-forest-labs/flux-3-image-klein";
const DIMENSIONS = 4096;
const MAX_REQUEST = 3 * 1024 * 1024;
const MAX_IMAGE = 2 * 1024 * 1024;
const MAX_RESPONSE = 12 * 1024 * 1024;
const MAX_ERROR_RESPONSE = 16 * 1024;
const CONTENT_CHECK_DETAILS = new Set([
  "This request or its output was declined by the model's content checks.",
  "The model declined the request or its output. Try a different description.",
]);
const headers = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
};

class ApiError extends Error {
  constructor(status, message, code = "request_failed", refusal = null) { super(message); this.status = status; this.code = code; this.refusal = refusal; }
}

function json(value, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { ...headers, "Content-Type": "application/json" } });
}

export function managedURL(value, port) {
  let url;
  try { url = new URL(value); } catch { throw new ApiError(422, `Paste the managed HTTPS public URL for port ${port}.`, "invalid_url"); }
  const pattern = new RegExp(`^port${port}-[a-z0-9]+\\.tunnel\\.applications\\.[a-z0-9-]+\\.nebius\\.cloud$`);
  if (url.protocol !== "https:" || !pattern.test(url.hostname) || url.port || url.username || url.password
      || url.search || url.hash || url.pathname.replace(/\/$/, "")) {
    throw new ApiError(422, `Use the Nebius managed public URL for port ${port}, without /v1, a token, or extra path.`, "invalid_url");
  }
  return url.origin;
}

function tokenValue(value) {
  if (typeof value !== "string" || value.length < 8 || value.length > 2048 || /\s|[^\x21-\x7e]/.test(value)) {
    throw new ApiError(422, "Paste the Endpoint authentication token.", "invalid_token");
  }
  return value;
}

async function boundedBytes(response, maximum) {
  const declared = Number(response.headers.get("Content-Length"));
  if (declared > maximum) {
    await response.body?.cancel().catch(() => {});
    throw new ApiError(413, "The response exceeds this demo’s size limit.", "response_too_large");
  }
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const parts = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maximum) throw new ApiError(413, "The response exceeds this demo’s size limit.", "response_too_large");
      parts.push(value);
    }
  } finally { await reader.cancel().catch(() => {}); }
  const result = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) { result.set(part, offset); offset += part.byteLength; }
  return result;
}

async function contentCheckRefusal(response) {
  // An HTTP 400 alone does not establish moderation. Accept only the runtime's
  // explicit refusal marker or its exact legacy messages, never arbitrary text.
  try {
    if (!/^application\/(?:[a-z0-9.+-]+\+)?json(?:\s*;|$)/i.test(response.headers.get("Content-Type") || "")) {
      await response.body?.cancel().catch(() => {});
      return null;
    }
    const data = JSON.parse(new TextDecoder().decode(await boundedBytes(response, MAX_ERROR_RESPONSE)));
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    const detail = data.detail?.code === "model_declined" ? data.detail
      : data.error?.code === "model_declined" ? data.error : data;
    if (detail.code !== "model_declined" && !CONTENT_CHECK_DETAILS.has(data.detail)) return null;
    return {
      stage: ["prompt", "reference", "output"].includes(detail.stage) ? detail.stage : "unknown",
      category: ["copyright_or_public_figure", "adult_content"].includes(detail.category) ? detail.category : "unknown",
    };
  } catch {
    // Error bodies can contain prompts, tokens or diagnostics. Neither parse
    // failures nor upstream text are reflected back to the visitor.
    return null;
  }
}

async function bodyJSON(request) {
  if (!request.headers.get("Content-Type")?.toLowerCase().startsWith("application/json")) {
    throw new ApiError(415, "Use an application/json request.");
  }
  const bytes = await boundedBytes(request, MAX_REQUEST);
  try {
    const body = JSON.parse(new TextDecoder().decode(bytes));
    if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error();
    return body;
  } catch { throw new ApiError(422, "The request is not valid JSON."); }
}

function textValue(value, maximum = 500) {
  if (typeof value !== "string" || !value.trim() || value.length > maximum) {
    throw new ApiError(422, `Enter a description between 1 and ${maximum} characters.`);
  }
  return value.trim();
}

function imageValue(value) {
  if (typeof value !== "string" || value.length > Math.ceil(MAX_IMAGE * 4 / 3) + 64
      || !/^data:image\/(jpeg|png|webp);base64,[A-Za-z0-9+/]+={0,2}$/.test(value)) {
    throw new ApiError(422, "Use a prepared JPG, PNG or WebP image smaller than 2 MiB.");
  }
  return value;
}

export function embeddingBody(content) {
  return { model: EMBEDDING_MODEL, encoding_format: "float", messages: [
    { role: "system", content: [{ type: "text", text: "Represent the user's input." }] },
    { role: "user", content },
    { role: "assistant", content: [{ type: "text", text: "" }] },
  ], continue_final_message: true, add_special_tokens: true };
}

export function normalizedVector(data) {
  const vector = data?.data?.length === 1 ? data.data[0]?.embedding : null;
  if (!Array.isArray(vector) || vector.length !== DIMENSIONS || vector.some(v => typeof v !== "number" || !Number.isFinite(v))) {
    throw new ApiError(422, "This Endpoint must return 4096-dimensional Qwen3-VL embeddings.", "wrong_embedding");
  }
  const norm = Math.sqrt(vector.reduce((sum, v) => sum + v * v, 0));
  if (!Number.isFinite(norm) || norm <= 0) throw new ApiError(422, "The Endpoint returned an invalid embedding.");
  return vector.map(v => v / norm);
}

export function createHandler({
  assets = {}, fetchImpl = globalThis.fetch, now = Date.now,
  clientIdentity = request => request.headers.get("CF-Connecting-IP") || "local",
  maxGenerationResponse = 6 * 1024 * 1024,
  maxGeneratedPNG = 4 * 1024 * 1024,
} = {}) {
  // Only short-lived, in-flight deduplication. This is not a durable job queue.
  const generations = new Map();
  const rates = new Map();

  async function upstream(base, token, path, body, timeout = 90000, maximum = MAX_RESPONSE) {
    let response;
    try {
      response = await fetchImpl(base + path, { method: body ? "POST" : "GET", redirect: "manual",
        headers: { Authorization: "Bearer " + token, Accept: "application/json", ...(body ? { "Content-Type": "application/json" } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}), signal: AbortSignal.timeout(timeout) });
    } catch { throw new ApiError(503, "The Endpoint could not be reached. Check its public URL and that both models are ready.", "endpoint_unavailable"); }
    if (!response.ok) {
      if ([400, 422].includes(response.status)) {
        const refusal = path === "/v1/images/generations" ? await contentCheckRefusal(response) : null;
        if (refusal) {
          const reason = refusal.stage === "prompt" ? "FLUX’s prompt check blocked this description."
            : refusal.stage === "output" ? "FLUX created an image, but its content check blocked the result."
            : "FLUX’s content checks blocked the prompt or generated image.";
          throw new ApiError(422, reason + " This can happen with everyday requests too. Nothing was added to your collection. Edit the description and approve a new attempt.", "model_declined", refusal);
        }
        await response.body?.cancel().catch(() => {});
        throw new ApiError(422, "The model API rejected the request format or settings. Check the Endpoint’s model service and try again.", "model_request_invalid");
      }
      await response.body?.cancel().catch(() => {});
      if ([401, 403].includes(response.status)) throw new ApiError(401, "The Endpoint rejected this token. Copy its Endpoint authentication token and try again.", "authentication_failed");
      if (response.status === 429) throw new ApiError(429, "The GPU is busy. Wait for the current request to finish, then try again.", "gpu_busy");
      if (response.status >= 300 && response.status < 400) throw new ApiError(422, "The Endpoint redirected this request. Copy its managed public URL again.", "redirect_rejected");
      throw new ApiError(503, "The model API is unavailable. Check the Endpoint is running and its model startup has finished.", "model_unavailable");
    }
    try { return JSON.parse(new TextDecoder().decode(await boundedBytes(response, maximum))); }
    catch (error) { if (error instanceof ApiError) throw error; throw new ApiError(502, "The Endpoint returned an unreadable model response."); }
  }

  async function models(base, token, expected) {
    const data = await upstream(base, token, "/v1/models", null, 20000, 256 * 1024);
    if (!Array.isArray(data.data) || !data.data.some(item => item.id === expected)) {
      throw new ApiError(422, `This port must serve ${expected}. Check the model and the public port URL.`, "wrong_model");
    }
  }

  async function embed(base, token, content) {
    return normalizedVector(await upstream(base, token, "/v1/embeddings", embeddingBody(content)));
  }

  function charge(request, generation = false) {
    const minute = Math.floor(now() / 60000);
    if (rates.size > 2048) for (const [key, entry] of rates) if (entry.minute !== minute) rates.delete(key);
    const identity = clientIdentity(request);
    const key = (generation ? "generation:" : "inference:") + identity;
    const entry = rates.get(key);
    const count = entry?.minute === minute ? entry.count : 0;
    if (count >= (generation ? 5 : 90)) throw new ApiError(429, "Too many requests. Wait a minute, then try again.", "request_limit");
    if (!entry && rates.size >= 4096) throw new ApiError(429, "The demo is busy. Please try again shortly.");
    rates.set(key, { minute, count: count + 1 });
  }

  async function generate(body, request) {
    const base = managedURL(body.base_url, 8001), token = tokenValue(body.token);
    const prompt = textValue(body.prompt, 2000);
    if (body.approved !== true || typeof body.request_id !== "string"
        || !/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(body.request_id)) {
      throw new ApiError(422, "Review and approve the prompt before generating an image.", "approval_required");
    }
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(base + "\n" + token + "\n" + body.request_id));
    const key = Array.from(new Uint8Array(digest), v => v.toString(16).padStart(2, "0")).join("");
    const previous = generations.get(key);
    if (previous) {
      if (previous.prompt !== prompt) throw new ApiError(409, "This approval was already used for another prompt. Review the new description first.");
      return previous.promise;
    }
    for (const [id, item] of generations) if (item.finished && now() - item.at > 60000) generations.delete(id);
    if ([...generations.values()].filter(item => !item.finished).length >= 2) {
      throw new ApiError(429, "The image queue is busy. Try again after the current image finishes.");
    }
    if (generations.size >= 32) {
      const finished = [...generations].find(([, item]) => item.finished);
      if (finished) generations.delete(finished[0]);
      else throw new ApiError(429, "The image queue is busy. Try again after the current image finishes.");
    }
    charge(request, true);
    const entry = { prompt, at: now(), finished: false, promise: null };
    entry.promise = (async () => {
      const data = await upstream(base, token, "/v1/images/generations", {
        model: GENERATION_MODEL, prompt, n: 1, size: "1024x1024", response_format: "b64_json",
      }, 240000, maxGenerationResponse);
      const value = data?.data?.length === 1 ? data.data[0]?.b64_json : null;
      if (typeof value !== "string" || value.length > Math.ceil(maxGeneratedPNG / 3) * 4 || value.length % 4 !== 0
          || !/^[A-Za-z0-9+/]+={0,2}$/.test(value) || !value.startsWith("iVBORw0KGgo")) {
        throw new ApiError(502, "The generation API did not return a valid PNG image.");
      }
      const first = atob(value.slice(0, 40));
      const bytes = Uint8Array.from(first, c => c.charCodeAt(0));
      const view = new DataView(bytes.buffer);
      if (bytes.length < 24 || first.slice(12, 16) !== "IHDR" || view.getUint32(16) > 1024 || view.getUint32(20) > 1024
          || view.getUint32(16) < 2 || view.getUint32(20) < 2) throw new ApiError(502, "The generated image dimensions are outside this demo’s limits.");
      return { image_data_url: "data:image/png;base64," + value, model: GENERATION_MODEL };
    })().finally(() => {
      entry.finished = true;
      entry.at = now();
      // Do not retain multi-megabyte image results in a shared Worker cache.
      // Keep only a small finished-attempt sentinel to prevent a silent repeat.
      entry.promise = Promise.reject(new ApiError(409, "This attempt already finished. If its image was not received, review and approve a new request; it may create another image.", "attempt_finished"));
      entry.promise.catch(() => {});
    });
    // Remember a failed/uncertain attempt briefly; a repeat must not silently
    // become a second generation. Different Worker instances cannot share it.
    entry.promise.catch(() => {});
    generations.set(key, entry);
    return entry.promise;
  }

  return { async fetch(request) {
    try {
      const url = new URL(request.url);
      if (request.method === "GET" && url.pathname === "/health") return json({ ok: true });
      if (!url.pathname.startsWith("/api/")) {
        if (!["GET", "HEAD"].includes(request.method)) return json({ detail: "Method not allowed." }, 405);
        const asset = assets[url.pathname === "/" ? "/index.html" : url.pathname];
        if (!asset) return json({ detail: "Page not found." }, 404);
        const bytes = Uint8Array.from(atob(asset.body), c => c.charCodeAt(0));
        return new Response(request.method === "HEAD" ? null : bytes, { headers: { ...headers, "Content-Type": asset.type } });
      }
      if (request.method !== "POST") return json({ detail: "Method not allowed." }, 405);
      const origin = request.headers.get("Origin");
      if ((origin && origin !== url.origin) || request.headers.get("Sec-Fetch-Site") === "cross-site") throw new ApiError(403, "Connect and search from this app’s own page.");
      if (!["/api/connect", "/api/connect-generation", "/api/embed", "/api/generate"].includes(url.pathname)) return json({ detail: "API route not found." }, 404);
      const body = await bodyJSON(request);
      if (url.pathname === "/api/connect") {
        charge(request);
        const base = managedURL(body.embedding_url, 8000), token = tokenValue(body.token);
        const generation = body.generation_url ? managedURL(body.generation_url, 8001) : null;
        const generationToken = generation ? tokenValue(body.generation_token || body.token) : null;
        await Promise.all([models(base, token, EMBEDDING_MODEL), ...(generation ? [models(generation, generationToken, GENERATION_MODEL)] : [])]);
        await embed(base, token, [{ type: "text", text: "Connection check" }]);
        return json({ embedding_model: EMBEDDING_MODEL, generation_model: generation ? GENERATION_MODEL : null, dimensions: DIMENSIONS });
      }
      if (url.pathname === "/api/connect-generation") {
        charge(request);
        const base = managedURL(body.generation_url, 8001), token = tokenValue(body.token);
        await models(base, token, GENERATION_MODEL);
        return json({ generation_url: base, generation_model: GENERATION_MODEL });
      }
      if (url.pathname === "/api/embed") {
        charge(request);
        const base = managedURL(body.base_url, 8000), token = tokenValue(body.token);
        const content = body.kind === "text" ? [{ type: "text", text: textValue(body.text) }]
          : body.kind === "image" ? [{ type: "image_url", image_url: { url: imageValue(body.image_data_url) } }, { type: "text", text: "" }]
          : null;
        if (!content) throw new ApiError(422, "Choose text or image embedding.");
        return json({ vector: await embed(base, token, content) });
      }
      return json(await generate(body, request));
    } catch (error) {
      if (error instanceof ApiError) return json({ detail: error.message, code: error.code, ...(error.refusal || {}) }, error.status);
      // Do not serialize SDK errors, credentials, prompt contents or image data.
      return json({ detail: "The request could not be completed. Check the connection and try again.", code: "request_failed" }, 500);
    }
  } };
}

export default createHandler();
