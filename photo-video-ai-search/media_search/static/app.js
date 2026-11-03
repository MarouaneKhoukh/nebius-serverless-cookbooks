"use strict";

const $ = id => document.getElementById(id);
const form = $("search-form");
const queryInput = $("query");
const searchButton = $("search-button");
const clearButton = $("clear-button");
const gallery = $("gallery");
const collection = $("collection");
const title = $("results-title");
const kicker = $("results-kicker");
const count = $("result-count");
const notice = $("notice");
const empty = $("empty-state");
const footnote = $("collection-footnote");
const loadMore = $("load-more");
const generationState = $("generation-state");
const generationRetry = $("generation-retry");
const promptReview = $("prompt-review");
const promptInput = $("generation-prompt");
const approveButton = $("approve-generation");
const generatedPreview = $("generated-preview");
const saveButton = $("save-generated");
const discardButton = $("discard-generated");
const suggestions = document.createElement("details");
suggestions.hidden = true;
suggestions.className = "collection-footnote";
gallery.after(suggestions);
const POLL_LIMIT_MS = 5 * 60 * 1000;
const ACTIVE_JOB_STATES = new Set(["submitting", "unconfirmed", "queued", "running", "ready", "saving"]);
let libraryItems = [];
let nextOffset = null;
let activeQuery = "";
let requestNumber = 0;
let showingLibrary = true;
let generationEnabled = false;
let sessionPromise = null;
let generationAction = null;
let lastSearch = null;
let draft = null;
let currentJob = null;
let pollNumber = 0;

function element(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}

function showNotice(message, error = false) {
  notice.textContent = message;
  notice.classList.toggle("error", error);
  notice.hidden = !message;
}

function setBusy(busy, searching = false) {
  collection.setAttribute("aria-busy", String(busy));
  searchButton.disabled = busy;
  searchButton.textContent = busy ? searching ? "Searching…" : "Loading…" : "Search ↗";
  loadMore.disabled = busy;
}

function showGeneration(state, heading, description, action = null, actionLabel = "Try again") {
  generationState.hidden = false;
  generationState.dataset.state = state;
  $("generation-title").textContent = heading;
  $("generation-description").textContent = description;
  generationAction = action;
  generationRetry.textContent = actionLabel;
  generationRetry.hidden = !action;
}

function updateCreateOffer() {
  const active = currentJob && ACTIVE_JOB_STATES.has(currentJob.status);
  $("create-offer").hidden = !lastSearch || !lastSearch.generationAvailable || Boolean(draft) || Boolean(active);
}

async function fetchJSON(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Accept": "application/json", ...options.headers } });
  let data;
  try { data = await response.json(); } catch (_) { data = null; }
  if (!response.ok) {
    const detail = data && (data.detail || data.error || data.message);
    const retryAfter = Number(response.headers.get("Retry-After"));
    const message = response.status === 429
      ? `The demo is busy or its usage limit has been reached. ${Number.isFinite(retryAfter) && retryAfter > 0 ? `Try again in ${Math.ceil(retryAfter)} seconds.` : "Please try again later."}`
      : typeof detail === "string" ? detail.slice(0, 300) : `The request failed (${response.status}).`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  if (!data || typeof data !== "object") throw new Error("The server returned an unreadable response.");
  return data;
}

async function postJSON(path, body) {
  if (!sessionPromise) {
    sessionPromise = fetchJSON("/api/session").then(data => {
      if (typeof data.csrf_token !== "string" || !data.csrf_token) throw new Error("Refresh this page to reconnect to the demo.");
      return data.csrf_token;
    }).catch(error => { sessionPromise = null; throw error; });
  }
  const csrfToken = await sessionPromise;
  try {
    return await fetchJSON(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
      body: JSON.stringify(body)
    });
  } catch (error) {
    if (error.status === 403) sessionPromise = null;
    // A timed-out POST may have succeeded. Only an explicit action retries it.
    throw error;
  }
}

function safeMediaURL(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value, window.location.origin);
    return url.origin === window.location.origin && url.pathname.startsWith("/media/") ? url.href : null;
  } catch (_) { return null; }
}

function safePreviewURL(value, job) {
  if (typeof value !== "string" || !job.id) return null;
  try {
    const url = new URL(value, window.location.origin);
    return url.origin === window.location.origin && url.pathname === `/api/generations/${encodeURIComponent(job.id)}/image` ? url.href : null;
  } catch (_) { return null; }
}

function makeCard(item, isSearch = false) {
  const isGenerated = item.generated === true;
  const related = isSearch && item.match_type === "related";
  const card = element("article", `media-card${isGenerated ? " is-generated" : ""}${related ? " is-related" : ""}`);
  const preview = element("div", "media-preview");
  const mediaURL = safeMediaURL(item.media_url);
  const thumbnailURL = safeMediaURL(item.thumbnail_url);
  const mediaTitle = String(item.title || item.prompt || item.source_name || "Untitled image");
  if (mediaURL || thumbnailURL) {
    const media = element("img");
    media.alt = mediaTitle;
    media.loading = "lazy";
    media.decoding = "async";
    media.src = thumbnailURL || mediaURL;
    if (mediaURL) {
      const link = element("a", "image-link");
      link.href = mediaURL;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.setAttribute("aria-label", `Open full image: ${mediaTitle} (new tab)`);
      link.append(media);
      preview.append(link);
    } else preview.append(media);
  } else preview.append(element("span", "source-name", "Preview unavailable"));
  preview.append(element("span", "media-type", isGenerated ? "AI-GENERATED" : "IMAGE"));
  const info = element("div", "media-info");
  info.append(element("h3", "", mediaTitle));
  info.append(element("p", "source-name", isGenerated ? "Created with FLUX 3 Image Klein" : String(item.source_name || "")));
  const detail = element("div", "media-detail");
  const reason = isSearch
    ? item.match_type === "named" ? "Name matches your search" : related ? "More to explore" : "Similar image"
    : isGenerated ? "Saved to your collection" : "Image";
  detail.append(element("span", "", reason));
  info.append(detail);
  if (isSearch && Number.isFinite(item.score)) {
    const diagnostics = element("details", "source-name");
    diagnostics.append(element("summary", "", "Search details"));
    diagnostics.append(element("p", "", `Visual cosine: ${item.score.toFixed(3)}. Used for ranking.`));
    if (item.match_type === "named") diagnostics.append(element("p", "", "Your search words appear in this image’s title or filename."));
    info.append(diagnostics);
  }
  card.append(preview, info);
  return card;
}

function updateCount(length, isSearch) {
  count.textContent = isSearch
    ? `${length} ${length === 1 ? "result" : "results"}${length ? " · closest first" : ""}`
    : `${length} ${length === 1 ? "image" : "images"} shown`;
}

function render(items, isSearch = false) {
  const primary = isSearch ? items.filter(item => item.match_type === "named" || item.match_type === "semantic") : items;
  const hasMatches = primary.length > 0;
  gallery.replaceChildren(...primary.map(item => makeCard(item, isSearch)));
  suggestions.replaceChildren();
  const scored = isSearch ? items.filter(item => Number.isFinite(item.score)) : [];
  suggestions.hidden = !scored.length;
  suggestions.open = false;
  if (scored.length) {
    const diagnostics = element("ul", "search-scores");
    for (const item of scored) {
      const accepted = item.match_type === "named" || item.match_type === "semantic";
      diagnostics.append(element("li", "", `${item.title || item.source_name || "Untitled image"}: ${item.score.toFixed(3)} · ${accepted ? "shown" : "below the display cutoff"}`));
    }
    suggestions.append(element("summary", "", "Search details"),
      element("p", "", "Cosine similarity ranks images; it is not a confidence percentage. Candidates below the display cutoff are not search results."), diagnostics);
  }
  title.textContent = isSearch
    ? hasMatches ? `Matches for “${activeQuery}”` : `No matching photos for “${activeQuery}”`
    : "The collection";
  kicker.textContent = isSearch ? "SEARCH RESULTS" : "YOUR LIBRARY";
  updateCount(primary.length, isSearch);
  footnote.hidden = isSearch ? !hasMatches : !items.length;
  footnote.textContent = isSearch
    ? "Search combines visual similarity with descriptive image names."
    : "Browse your images or describe what you want to find.";
  empty.hidden = hasMatches;
  $("empty-title").textContent = isSearch ? "No matching photos." : generationEnabled ? "What would you like to see?" : "Make your images searchable.";
  $("empty-description").textContent = isSearch
    ? "Try another description, return to your collection, add your own photos, or choose to create an image."
    : generationEnabled
      ? "Search for an image above, or add your own photos to the collection."
      : "Add a folder of images from your terminal, then refresh this page.";
  $("ingest-command").hidden = isSearch || generationEnabled || libraryItems.length > 0;
  clearButton.hidden = !isSearch;
  loadMore.hidden = isSearch || !nextOffset;
}

function openPromptReview(query = lastSearch && lastSearch.query, prompt = query) {
  if (!query || currentJob && ACTIVE_JOB_STATES.has(currentJob.status)) return;
  draft = { query, requestId: crypto.randomUUID() };
  promptInput.value = prompt;
  promptReview.hidden = false;
  generationState.hidden = true;
  generatedPreview.hidden = true;
  approveButton.disabled = !promptInput.value.trim();
  updateCreateOffer();
  promptInput.focus();
  promptReview.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function cancelPromptReview() {
  draft = null;
  promptReview.hidden = true;
  updateCreateOffer();
  $("create-image").focus();
}

function setPreviewActions(busy, retrySave = false) {
  saveButton.disabled = busy;
  discardButton.disabled = busy;
  saveButton.textContent = busy && currentJob && currentJob.status === "saving" ? "Adding to collection…" : retrySave ? "Retry saving" : "Add to collection";
  discardButton.textContent = busy && currentJob && currentJob.discarding ? "Discarding…" : "Discard";
}

function renderPreview(job, saved = false) {
  const url = saved && job.item ? safeMediaURL(job.item.media_url) : safePreviewURL(job.preview && job.preview.media_url, job);
  if (!url) throw new Error("The image preview is unavailable. Check its status again.");
  generatedPreview.hidden = false;
  $("generated-image").src = url;
  $("generated-image").alt = `AI-generated image: ${job.prompt}`;
  $("preview-prompt").textContent = job.prompt;
  $("preview-kicker").textContent = saved ? "ADDED TO YOUR COLLECTION" : "STEP 2 · KEEP IT OR DISCARD IT";
  $("preview-title").textContent = saved ? "Saved and ready to search." : "Add this image to your collection?";
  $("preview-description").textContent = saved ? "This image is now part of your collection. Find it again with another search." : "This preview is only for you. Save it to make it searchable in the collection.";
  $("preview-actions").hidden = saved;
  setPreviewActions(job.status === "saving");
}

async function refreshLibraryAfterSave(job) {
  // Refresh the collection without replacing a newer search or losing this preview.
  const viewRequest = requestNumber;
  const data = await fetchJSON("/api/gallery?limit=24&kind=image");
  if (!Array.isArray(data.items)) return;
  libraryItems = data.items;
  nextOffset = typeof data.next_offset === "string" && data.next_offset ? data.next_offset : null;
  if (showingLibrary && viewRequest === requestNumber) render(libraryItems);
  if (currentJob === job && job.status === "saved") {
    $("preview-description").textContent = `This image is now searchable in your collection. ${libraryItems.length}${nextOffset ? "+" : ""} ${libraryItems.length === 1 ? "image" : "images"} in the collection.`;
  }
}

async function acceptJobState(job, result) {
  if (currentJob !== job) return true;
  job.status = result.status;
  if (typeof result.prompt === "string") job.prompt = result.prompt;
  if (result.preview && typeof result.preview === "object") job.preview = result.preview;
  if (result.item && typeof result.item === "object") job.item = result.item;
  updateCreateOffer();
  if (job.status === "ready") {
    renderPreview(job);
    generationState.hidden = true;
    return true;
  }
  if (job.status === "saved") {
    renderPreview(job, true);
    showGeneration("succeeded", "Added to your collection.", "You chose to keep this image. It’s ready for your next search.");
    refreshLibraryAfterSave(job).catch(() => {
      if (currentJob === job) $("preview-description").textContent = "The image is saved. Clear your search to refresh the collection.";
    });
    return true;
  }
  if (job.status === "discarded") {
    generatedPreview.hidden = true;
    $("generated-image").removeAttribute("src");
    showGeneration("succeeded", "Preview discarded.", "No image was added to your collection.");
    return true;
  }
  if (job.status === "failed") {
    showGeneration("failed", "The image couldn’t be created.", typeof result.error === "string" ? result.error.slice(0, 300) : "Please review the prompt and try again.", () => openPromptReview(job.query, job.prompt), "Review prompt");
    return true;
  }
  if (!["queued", "running", "saving"].includes(job.status)) throw new Error("The image status is unavailable. Check progress again in a moment.");
  if (job.status === "saving") {
    showGeneration("pending", "Adding the image to your collection…", "Your approved image is being made searchable.");
    if (job.preview) renderPreview(job);
  } else {
    showGeneration("pending", "Creating your image…", "You’ll see a preview before deciding whether to save it. You can keep searching while it runs.");
  }
  return false;
}

async function pollJob(job) {
  const currentPoll = ++pollNumber;
  const started = Date.now();
  try {
    while (currentJob === job && currentPoll === pollNumber && Date.now() - started < POLL_LIMIT_MS) {
      const result = await fetchJSON(`/api/generations/${encodeURIComponent(job.id)}`, { signal: AbortSignal.timeout(30000) });
      if (currentPoll !== pollNumber || currentJob !== job) return;
      if (await acceptJobState(job, result)) return;
      await new Promise(resolve => setTimeout(resolve, 2500));
    }
    if (currentJob === job && currentPoll === pollNumber) showGeneration("paused", "Your image is still being prepared.", "Check progress when you’re ready. It won’t be added to the collection automatically.", () => pollJob(job), "Check progress");
  } catch (error) {
    if (currentJob === job && currentPoll === pollNumber) showGeneration("failed", "We couldn’t check the image yet.", error.message, () => pollJob(job), "Check progress");
  }
}

async function reviewRejectedJob(job, refreshSearch = false) {
  if (currentJob !== job || job.status !== "rejected") return;
  if (refreshSearch) {
    const expectedRequest = requestNumber + 1;
    queryInput.value = job.query;
    await search();
    if (currentJob !== job || requestNumber !== expectedRequest) return;
    if (!lastSearch || lastSearch.query !== job.query) {
      showGeneration("failed", "The search needs to reconnect first.", "Try refreshing the search again. Your image has not been created.", () => reviewRejectedJob(job, true), "Refresh search and review");
      return;
    }
  }
  openPromptReview(job.query, job.prompt);
}

async function submitApprovedJob(job) {
  if (currentJob !== job || job.submitting || job.id) return;
  job.submitting = true;
  job.status = "submitting";
  updateCreateOffer();
  showGeneration("pending", "Sending your approved prompt…", "The image will be shown as a preview. You choose whether to keep it.");
  try {
    const result = await postJSON("/api/generations", { query: job.query, prompt: job.prompt, approved: true, request_id: job.requestId, kind: "image" });
    if (currentJob !== job) return;
    if (typeof result.id !== "string" || !result.id) throw new Error("The image request could not be confirmed.");
    job.id = result.id;
    if (!await acceptJobState(job, result)) pollJob(job);
  } catch (error) {
    if (currentJob !== job) return;
    if (job.id) {
      showGeneration("failed", "We couldn’t check the image yet.", error.message, () => pollJob(job), "Check progress");
    } else if (Number.isInteger(error.status) && error.status >= 400 && error.status < 500 && ![408, 499].includes(error.status)) {
      // A rejected request did not create a job. Let the reader edit or cancel;
      // stale sessions/search decisions need a fresh search before approval.
      job.status = "rejected";
      const refreshSearch = [401, 403, 409].includes(error.status);
      showGeneration("failed", "The image request wasn’t started.", error.message,
        () => reviewRejectedJob(job, refreshSearch), refreshSearch ? "Refresh search and review" : "Review prompt");
    } else {
      job.status = "unconfirmed";
      showGeneration("failed", "We couldn’t confirm the image request.", `${error.message} Retrying checks the same approved request.`, () => submitApprovedJob(job), "Retry approved request");
    }
  } finally {
    job.submitting = false;
    updateCreateOffer();
  }
}

function approveGeneration() {
  if (!draft || !promptInput.value.trim() || currentJob && ACTIVE_JOB_STATES.has(currentJob.status)) return;
  currentJob = { id: null, query: draft.query, prompt: promptInput.value.trim(), requestId: draft.requestId, status: "submitting", preview: null, item: null, submitting: false, mutating: false };
  draft = null;
  promptReview.hidden = true;
  approveButton.disabled = true;
  submitApprovedJob(currentJob);
}

async function mutatePreview(action) {
  const job = currentJob;
  if (!job || !job.id || job.mutating || job.status !== "ready") return;
  job.mutating = true;
  job.discarding = action === "discard";
  if (action === "save") job.status = "saving";
  setPreviewActions(true);
  showGeneration("pending", action === "save" ? "Adding the image to your collection…" : "Discarding the preview…", action === "save" ? "Your image is being made searchable." : "It won’t be added to your collection.");
  try {
    const result = await postJSON(`/api/generations/${encodeURIComponent(job.id)}/${action}`, {});
    if (currentJob !== job) return;
    if (!await acceptJobState(job, result)) pollJob(job);
  } catch (error) {
    if (currentJob !== job) return;
    // A lost save response must never lead to another generation request.
    try {
      const result = await fetchJSON(`/api/generations/${encodeURIComponent(job.id)}`, { signal: AbortSignal.timeout(15000) });
      if (currentJob !== job) return;
      if (result.status !== "ready") {
        if (!await acceptJobState(job, result)) pollJob(job);
        return;
      }
      await acceptJobState(job, result);
    } catch (_) { job.status = "ready"; }
    setPreviewActions(false, action === "save");
    showGeneration("failed", action === "save" ? "We couldn’t confirm the save." : "We couldn’t discard the preview yet.", `${error.message} Your image won’t be generated again.`, () => mutatePreview(action), action === "save" ? "Retry saving" : "Retry discard");
  } finally {
    job.mutating = false;
    job.discarding = false;
    updateCreateOffer();
    if (currentJob === job && job.status === "ready") setPreviewActions(false, saveButton.textContent === "Retry saving");
  }
}

async function search() {
  const query = queryInput.value.trim();
  if (!query) { clearSearch(); return; }
  const currentRequest = ++requestNumber;
  showingLibrary = false;
  lastSearch = null;
  if (draft) { draft = null; promptReview.hidden = true; }
  updateCreateOffer();
  setBusy(true, true);
  loadMore.hidden = true;
  showNotice("Finding the closest images in your collection…");
  try {
    const data = await postJSON("/api/search", { query, kind: "image", limit: 12 });
    if (currentRequest !== requestNumber) return;
    if (!Array.isArray(data.items)) throw new Error("The search response did not include image results.");
    activeQuery = query;
    render(data.items, true);
    lastSearch = { query, generationAvailable: data.generation_available === true };
    updateCreateOffer();
    showNotice("");
  } catch (error) {
    if (currentRequest !== requestNumber) return;
    showNotice(`Search could not complete. ${error.message}`, true);
    clearButton.hidden = false;
  } finally {
    if (currentRequest === requestNumber) setBusy(false);
  }
}

function clearSearch() {
  activeQuery = "";
  lastSearch = null;
  showingLibrary = true;
  queryInput.value = "";
  if (draft) { draft = null; promptReview.hidden = true; }
  updateCreateOffer();
  loadLibrary();
}

form.addEventListener("submit", event => { event.preventDefault(); search(); });
clearButton.addEventListener("click", () => { clearSearch(); queryInput.focus(); });
generationRetry.addEventListener("click", () => { if (generationAction) generationAction(); });
$("create-image").addEventListener("click", () => openPromptReview());
$("cancel-generation").addEventListener("click", cancelPromptReview);
approveButton.addEventListener("click", approveGeneration);
promptInput.addEventListener("input", () => { approveButton.disabled = !promptInput.value.trim(); });
saveButton.addEventListener("click", () => mutatePreview("save"));
discardButton.addEventListener("click", () => mutatePreview("discard"));
queryInput.addEventListener("search", () => { if (!queryInput.value.trim()) clearSearch(); });
loadMore.addEventListener("click", () => loadLibrary(false));

async function loadStatus() {
  try {
    const data = await fetchJSON("/api/status");
    generationEnabled = data.generation_enabled === true;
    const parts = [];
    if (data.model) parts.push(String(data.model));
    if (generationEnabled) parts.push("FLUX 3 Image Klein");
    parts.push("Powered by Nebius Serverless AI");
    $("model-note").textContent = parts.join(" · ");
    $("hero-kicker").textContent = generationEnabled ? "SEARCH YOUR IMAGES. CREATE SOMETHING NEW." : "YOUR PHOTOS. ONE SEARCH.";
    $("hero-subtitle").textContent = generationEnabled ? "Or create one." : "Describe what you see.";
    $("intro").textContent = generationEnabled
      ? "Describe an image to find the closest photos in your collection. Want something new? Review a prompt, create a preview with FLUX 3, and decide whether to keep it."
      : "Search your photos by meaning, from “a dog at the beach” to “someone making coffee.” Qwen3-VL embeddings connect your words to images.";
    $("privacy-note").hidden = !generationEnabled;
    if (showingLibrary && !libraryItems.length) render([]);
  } catch (_) { /* Browsing and search do not depend on the status display. */ }
}

async function loadLibrary(reset = true) {
  if (!reset && !nextOffset) return;
  const currentRequest = ++requestNumber;
  showingLibrary = true;
  const parameters = new URLSearchParams({ limit: "24", kind: "image" });
  if (!reset) parameters.set("offset", nextOffset);
  setBusy(true);
  showNotice(reset ? "Loading your collection…" : "Loading more images…");
  try {
    const data = await fetchJSON(`/api/gallery?${parameters}`);
    if (currentRequest !== requestNumber) return;
    if (!Array.isArray(data.items)) throw new Error("The gallery response did not include images.");
    nextOffset = typeof data.next_offset === "string" && data.next_offset ? data.next_offset : null;
    if (reset) {
      libraryItems = data.items;
      render(libraryItems);
    } else {
      const seen = new Set(libraryItems.map(item => item.id));
      const added = data.items.filter(item => !seen.has(item.id));
      libraryItems.push(...added);
      gallery.append(...added.map(item => makeCard(item)));
      updateCount(libraryItems.length, false);
      loadMore.hidden = !nextOffset;
    }
    showNotice("");
  } catch (error) {
    if (currentRequest === requestNumber) {
      if (reset) { libraryItems = []; nextOffset = null; render([]); }
      showNotice(`The collection is unavailable. Please try again in a moment. ${error.message}`, true);
    }
  } finally {
    if (currentRequest === requestNumber) setBusy(false);
  }
}

loadStatus();
loadLibrary();
