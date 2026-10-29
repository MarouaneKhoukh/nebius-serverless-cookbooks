"use strict";

const form = document.getElementById("search-form");
const queryInput = document.getElementById("query");
const searchButton = document.getElementById("search-button");
const clearButton = document.getElementById("clear-button");
const gallery = document.getElementById("gallery");
const collection = document.getElementById("collection");
const title = document.getElementById("results-title");
const kicker = document.getElementById("results-kicker");
const count = document.getElementById("result-count");
const notice = document.getElementById("notice");
const empty = document.getElementById("empty-state");
const footnote = document.getElementById("collection-footnote");
const loadMore = document.getElementById("load-more");
let libraryItems = [];
let nextOffset = null;
let totalPoints = null;
let activeQuery = "";
let requestNumber = 0;
let showingLibrary = true;

function element(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}

function selectedKind() {
  return form.elements.kind.value;
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

async function fetchJSON(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Accept": "application/json", ...options.headers } });
  let data;
  try { data = await response.json(); } catch (_) { data = null; }
  if (!response.ok) {
    const detail = data && (data.detail || data.error || data.message);
    throw new Error(typeof detail === "string" ? detail : `The request failed (${response.status}).`);
  }
  if (!data || typeof data !== "object") throw new Error("The server returned an unreadable response.");
  return data;
}

function safeMediaURL(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value, window.location.origin);
    return url.origin === window.location.origin && url.pathname.startsWith("/media/") ? url.href : null;
  } catch (_) { return null; }
}

function timestamp(value) {
  const seconds = Math.max(0, Number(value) || 0);
  const whole = Math.floor(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const remainder = String(whole % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${remainder}` : `${minutes}:${remainder}`;
}

function makeCard(item) {
  const card = element("article", "media-card");
  const preview = element("div", "media-preview");
  const isVideo = item.kind === "video";
  const mediaURL = safeMediaURL(item.media_url);
  const thumbnailURL = safeMediaURL(item.thumbnail_url);
  const mediaTitle = String(item.title || item.source_name || "Untitled media");
  if (mediaURL || thumbnailURL) {
    const media = element(isVideo && mediaURL ? "video" : "img");
    if (media.tagName === "VIDEO") {
      media.controls = true;
      media.preload = "metadata";
      media.playsInline = true;
      media.setAttribute("aria-label", mediaTitle);
      if (thumbnailURL) media.poster = thumbnailURL;
      media.src = mediaURL;
    } else {
      media.alt = mediaTitle;
      media.loading = "lazy";
      media.decoding = "async";
      media.src = thumbnailURL || mediaURL;
    }
    if (!isVideo && mediaURL) {
      const link = element("a", "image-link");
      link.href = mediaURL;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.setAttribute("aria-label", `Open full image: ${mediaTitle} (new tab)`);
      link.append(media);
      preview.append(link);
    } else {
      preview.append(media);
    }
  } else {
    preview.append(element("span", "source-name", "Preview unavailable"));
  }
  preview.append(element("span", "media-type", isVideo ? "VIDEO CLIP" : "PHOTO"));
  const info = element("div", "media-info");
  info.append(element("h3", "", mediaTitle));
  info.append(element("p", "source-name", String(item.source_name || "")));
  const detail = element("div", "media-detail");
  if (isVideo && Number.isFinite(item.start_seconds)) {
    const end = Number.isFinite(item.end_seconds) ? ` – ${timestamp(item.end_seconds)}` : "";
    detail.append(element("span", "clip-time", `${timestamp(item.start_seconds)}${end}`));
  } else {
    detail.append(element("span", "", isVideo ? "Video" : "Image"));
  }
  if (Number.isFinite(item.score)) {
    const similarity = element("span", "similarity");
    similarity.append(document.createTextNode("Similarity "), element("b", "", item.score.toFixed(3)));
    detail.append(similarity);
  }
  info.append(detail);
  card.append(preview, info);
  return card;
}

function updateCount(length, isSearch) {
  count.textContent = isSearch
    ? `${length} ${length === 1 ? "result" : "results"} · best matches first`
    : selectedKind() === "all" && totalPoints !== null
      ? `${length} of ${totalPoints} ${totalPoints === 1 ? "item" : "items"}`
      : `${length} ${length === 1 ? "item" : "items"} shown`;
}

function render(items, isSearch = false) {
  gallery.replaceChildren(...items.map(makeCard));
  title.textContent = isSearch ? `Matches for “${activeQuery}”` : "The collection";
  kicker.textContent = isSearch ? "SEARCH RESULTS" : "YOUR LIBRARY";
  updateCount(items.length, isSearch);
  footnote.hidden = !items.length;
  footnote.textContent = isSearch
    ? "Similarity scores rank matches for this query. They are not confidence percentages."
    : "Browse indexed media or describe a moment to search across the collection.";
  empty.hidden = items.length > 0;
  document.getElementById("empty-title").textContent = isSearch ? "No matching media yet." : selectedKind() !== "all" ? "No media of this type yet." : "Make your media searchable.";
  document.getElementById("empty-description").textContent = isSearch
    ? "Try another description or choose a different media type. If this collection is empty, ingest your files first."
    : selectedKind() !== "all"
      ? "Choose another media type, or ingest a folder containing photos and videos."
      : "Add a folder of photos and videos from your terminal, then refresh this page.";
  document.getElementById("ingest-command").hidden = libraryItems.length > 0;
  clearButton.hidden = !isSearch;
  loadMore.hidden = isSearch || !nextOffset;
}

async function search() {
  const query = queryInput.value.trim();
  if (!query) { clearSearch(); return; }
  const currentRequest = ++requestNumber;
  showingLibrary = false;
  setBusy(true, true);
  loadMore.hidden = true;
  showNotice("Embedding your description and finding matching media…");
  try {
    const data = await fetchJSON("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, kind: selectedKind(), limit: 12 })
    });
    if (currentRequest !== requestNumber) return;
    if (!Array.isArray(data.items)) throw new Error("The search response did not include media results.");
    activeQuery = query;
    render(data.items, true);
    showNotice("");
  } catch (error) {
    if (currentRequest !== requestNumber) return;
    showNotice(`Search could not complete. Check that Qdrant is running and your embedding Endpoint is ready, then retry. ${error.message}`, true);
    clearButton.hidden = false;
  } finally {
    if (currentRequest === requestNumber) setBusy(false);
  }
}

function clearSearch() {
  activeQuery = "";
  showingLibrary = true;
  queryInput.value = "";
  loadLibrary();
}

form.addEventListener("submit", event => { event.preventDefault(); search(); });
clearButton.addEventListener("click", () => { clearSearch(); queryInput.focus(); });
form.querySelectorAll('input[name="kind"]').forEach(input => {
  input.addEventListener("change", () => {
    if (activeQuery || queryInput.value.trim()) search();
    else loadLibrary();
  });
});
queryInput.addEventListener("search", () => { if (!queryInput.value.trim()) clearSearch(); });

loadMore.addEventListener("click", () => loadLibrary(false));

async function loadStatus() {
  try {
    const data = await fetchJSON("/api/status");
    const parts = [];
    if (data.model) parts.push(String(data.model));
    if (Number.isFinite(data.dimensions)) parts.push(`${data.dimensions.toLocaleString()} dimensions`);
    parts.push("Embeddings on Nebius Serverless AI");
    document.getElementById("model-note").textContent = parts.join(" · ");
    if (Number.isFinite(data.points) && data.points >= 0) {
      totalPoints = data.points;
      if (showingLibrary) updateCount(libraryItems.length, false);
    }
  } catch (_) { /* The collection can still be browsed if status is unavailable. */ }
}

async function loadLibrary(reset = true) {
  if (!reset && !nextOffset) return;
  const currentRequest = ++requestNumber;
  showingLibrary = true;
  const parameters = new URLSearchParams({ limit: "24", kind: selectedKind() });
  if (!reset) parameters.set("offset", nextOffset);
  setBusy(true);
  showNotice(reset ? "Loading your collection…" : "Loading more media…");
  try {
    const data = await fetchJSON(`/api/gallery?${parameters}`);
    if (currentRequest !== requestNumber) return;
    if (!Array.isArray(data.items)) throw new Error("The gallery response did not include media.");
    nextOffset = typeof data.next_offset === "string" && data.next_offset ? data.next_offset : null;
    if (reset) {
      libraryItems = data.items;
      render(libraryItems);
    } else {
      // Keep existing cards (and video playback state) when adding another page.
      const seen = new Set(libraryItems.map(item => item.id));
      const added = data.items.filter(item => !seen.has(item.id));
      libraryItems.push(...added);
      gallery.append(...added.map(makeCard));
      updateCount(libraryItems.length, false);
      loadMore.hidden = !nextOffset;
    }
    showNotice("");
  } catch (error) {
    if (currentRequest === requestNumber) {
      if (reset) {
        libraryItems = [];
        nextOffset = null;
        render([]);
      }
      showNotice(reset
        ? `The collection is unavailable. Start Qdrant and check your local configuration, then refresh this page. ${error.message}`
        : `Could not load more media. Retry using the button below, or check that Qdrant is running. ${error.message}`, true);
    }
  } finally {
    if (currentRequest === requestNumber) setBusy(false);
  }
}

loadStatus();
loadLibrary();
