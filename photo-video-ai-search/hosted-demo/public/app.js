"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const MAX_PHOTOS = 20;
  const DIMENSIONS = 4096;
  const SEEDS = [
    { id: "example-coffee", title: "Coffee beans", source_name: "coffee-beans.jpg" },
    { id: "example-mountain", title: "Mountain lake", source_name: "mountain-lake.jpg" },
    { id: "example-city", title: "City at night", source_name: "city-at-night.jpg" }
  ];
  const vectors = new Map();
  const requests = new Set();
  let photos = SEEDS.map(photo => ({ ...photo, url: `/examples/${photo.source_name}`, example: true }));
  let database = null;
  let initialized = false;
  let connection = null;
  let connectionEpoch = 0;
  let connecting = false;
  let indexing = false;
  let uploading = false;
  let searching = false;
  let searchEpoch = 0;
  let pendingQuery = "";
  let pendingCreation = null;
  let lastSearch = null;
  let draft = null;
  let generationBusy = false;
  let generationAmbiguous = false;
  let generationAction = null;
  let preview = null;
  let generationIntent = null;
  let generationConnectEpoch = 0;
  let generationConnecting = false;
  let creationDeclinedSearch = -1;

  function node(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined) item.textContent = text;
    return item;
  }

  function notice(message, error = false) {
    $("notice").textContent = message;
    $("notice").classList.toggle("error", error);
    $("notice").hidden = !message;
  }

  function storageWarning() {
    $("storage-notice").textContent = "This browser couldn’t save the collection on this device. Photos added now will stay in this tab only. Keep the tab open, or allow browser storage and reload before adding photos.";
    $("storage-notice").hidden = false;
  }

  function safeImage(value) {
    return typeof value === "string" && /^data:image\/(?:jpeg|png|webp);base64,[A-Za-z0-9+/=]+$/.test(value) && value.length <= 12 * 1024 * 1024;
  }

  function photoSource(photo) {
    if (safeImage(photo.data_url)) return photo.data_url;
    return photo.example && SEEDS.some(seed => seed.id === photo.id) ? `/examples/${photo.source_name}` : "";
  }

  function card(photo, result = false) {
    const item = node("article", `media-card${photo.generated ? " is-generated" : ""}`);
    const imageWrap = node("div", "media-preview");
    const image = node("img");
    image.src = photoSource(photo);
    image.alt = String(photo.title || "Photo").slice(0, 250);
    image.loading = "lazy";
    image.decoding = "async";
    imageWrap.append(image, node("span", "media-type", photo.generated ? "AI-GENERATED" : photo.example ? "EXAMPLE PHOTO" : "YOUR PHOTO"));
    const info = node("div", "media-info");
    info.append(node("h3", "", photo.title || "Untitled photo"), node("p", "", photo.generated ? "Created with FLUX · saved by you" : photo.source_name || ""));
    const detail = node("div", "media-detail");
    if (result) {
      const label = photo.match_type === "named" ? "Name match" : "Visual match";
      detail.append(node("span", "match-label", label));
    } else detail.append(node("span", "", vectors.has(photo.id) ? "Ready to search" : "On this device"));
    info.append(detail);
    item.append(imageWrap, info);
    return item;
  }

  function renderCollection() {
    $("photo-count").textContent = `${photos.length} ${photos.length === 1 ? "photo" : "photos"}`;
    if (!lastSearch) {
      $("collection-kicker").textContent = "YOUR COLLECTION";
      $("collection-title").textContent = photos.length === 3 && photos.every(photo => photo.example) ? "A few photos to start with." : "Your photo collection.";
      $("gallery").replaceChildren(...photos.map(photo => card(photo)));
      $("results-note").hidden = true;
      $("search-details").hidden = true;
      $("clear-search").hidden = true;
      $("empty-state").hidden = photos.length > 0;
      $("empty-title").textContent = "No photos to show yet.";
      $("empty-description").textContent = "Add a photo to start your collection.";
      $("collection-note").textContent = "Example photos are included. Photos you add stay in this browser; your Endpoint handles the embeddings.";
    } else {
      const ranked = lastSearch.result;
      const matches = ranked.items.filter(item => item.match_type !== "related");
      $("collection-kicker").textContent = "SEARCH RESULTS";
      $("collection-title").textContent = matches.length ? `Matches for “${lastSearch.query}”` : `No matching photos for “${lastSearch.query}”`;
      $("gallery").replaceChildren(...matches.map(photo => card(photo, true)));
      $("results-note").hidden = !matches.length;
      $("results-note").textContent = ranked.match_basis === "named"
        ? "Found photos matching your description using names and visual similarity."
        : "Found by visual similarity to your description. The closest matches appear first.";
      $("collection-note").textContent = "Search combines Qwen3-VL visual similarity with words in photo names.";
      const scored = ranked.items.filter(photo => Number.isFinite(photo.score));
      $("search-details-list").replaceChildren(...scored.map(photo => {
        const row = node("li");
        const status = photo.match_type === "related" ? "Below match threshold" : photo.match_type === "named" ? "Name match" : "Visual match";
        row.append(node("span", "", photo.title || "Untitled photo"), node("span", "", `${photo.score.toFixed(3)} · ${status}`));
        return row;
      }));
      $("search-details").hidden = !scored.length;
      $("clear-search").hidden = false;
      $("empty-state").hidden = matches.length > 0;
      $("empty-title").textContent = "No relevant photos found.";
      $("empty-description").textContent = "Try another description or add more photos to your collection.";
      $("empty-create-question").textContent = `Want to create an image of “${lastSearch.query}”?`;
    }
    updateControls();
  }

  function updateControls() {
    const busy = connecting || indexing || uploading || Boolean(preview && preview.saving);
    $("search-button").disabled = busy || searching || !initialized;
    $("search-button").textContent = searching ? "Searching…" : "Search ↗";
    $("add-photos").disabled = busy || !initialized || photos.length >= MAX_PHOTOS;
    $("connect-button").disabled = busy;
    $("connect-button").textContent = connection && connection.ready ? "Connection" : "Connect endpoint";
    $("disconnect-button").hidden = !connection && !connecting && !indexing;
    const badge = $("connection-badge");
    badge.classList.toggle("ready", Boolean(connection && connection.ready && connection.generation_url));
    badge.classList.toggle("search-ready", Boolean(connection && connection.ready && !connection.generation_url));
    badge.classList.toggle("busy", busy);
    $("connection-label").textContent = connecting ? "Checking connection…" : indexing ? "Indexing photos…" : connection && connection.ready ? connection.generation_url ? "Search + creation ready" : "Search ready · Creation not connected" : "Not connected";
    $("connection-hint").textContent = connection && connection.ready
      ? `${vectors.size} photos ready to search. ${connection.generation_url ? "FLUX is ready to create images from your approved prompts." : "Choose Create an image to connect FLUX and complete your setup."}`
      : "Search your photos or create something new. We’ll guide you through connecting your Nebius Endpoints.";
    $("create-from-description").disabled = busy || searching || !initialized || generationBusy || Boolean(preview && !preview.saved);
    const canOffer = Boolean(lastSearch && connection && connection.ready && !searching && !draft && !generationIntent && !generationBusy && !(preview && !preview.saved));
    const hasMatches = Boolean(lastSearch && lastSearch.result.items.some(item => item.match_type !== "related"));
    $("create-offer").hidden = !canOffer || !hasMatches;
    $("empty-create").hidden = !canOffer || hasMatches || creationDeclinedSearch === searchEpoch;
    $("submit-generation-connect").disabled = generationConnecting;
    $("submit-generation-connect").textContent = generationConnecting ? "Connecting…" : "Connect and review prompt";
    $("approve-generation").disabled = !draft || !$("generation-prompt").value.trim() || generationBusy || !connection || !connection.ready;
    if (preview && !preview.saved) {
      $("save-image").textContent = preview.saving ? "Adding to collection…" : connection && connection.ready ? "Add to collection" : "Reconnect to save";
      $("save-image").disabled = Boolean(preview.saving || busy);
      $("discard-image").disabled = Boolean(preview.saving);
    }
    document.querySelectorAll("[data-query]").forEach(button => { button.disabled = busy || searching || !initialized; });
  }

  function showIndexProgress(done, total, title = "Indexing your photos") {
    $("index-progress").hidden = false;
    $("index-title").textContent = title;
    $("index-description").textContent = `${done} of ${total} photos indexed with your Qwen3-VL Endpoint.`;
    $("index-meter").max = Math.max(total, 1);
    $("index-meter").value = done;
  }

  function abortRequests(kinds = null) {
    for (const request of requests) if (!kinds || kinds.includes(request.kind)) request.controller.abort();
  }

  async function api(path, body, kind, timeoutMs = 120000) {
    const controller = new AbortController();
    const request = { controller, kind };
    requests.add(request);
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/json" }, body: JSON.stringify(body), signal: controller.signal, credentials: "same-origin", cache: "no-store" });
      let result;
      try { result = await response.json(); } catch (_) { result = null; }
      if (!response.ok) {
        const error = new Error(result && typeof result.detail === "string" ? result.detail.slice(0, 350) : `The request failed (${response.status}).`);
        error.status = response.status;
        error.code = result && typeof result.code === "string" ? result.code : "";
        throw error;
      }
      if (!result || typeof result !== "object") throw new Error("The Endpoint returned an unreadable response.");
      return result;
    } finally { clearTimeout(timer); requests.delete(request); }
  }

  function normalizedVector(raw) {
    if (!Array.isArray(raw) || raw.length !== DIMENSIONS || raw.some(value => !Number.isFinite(value))) throw new Error("This Endpoint did not return the expected Qwen3-VL embedding.");
    const length = Math.sqrt(raw.reduce((sum, value) => sum + value * value, 0));
    if (!(length > 0)) throw new Error("The Endpoint returned an empty embedding.");
    return Float32Array.from(raw, value => value / length);
  }

  async function embed(kind, value, config, epoch) {
    if (epoch !== connectionEpoch) throw new DOMException("Connection changed", "AbortError");
    const result = await api("/api/embed", { base_url: config.embedding_url, token: config.token, kind, ...(kind === "text" ? { text: value } : { image_data_url: value }) }, "embed");
    if (epoch !== connectionEpoch) throw new DOMException("Connection changed", "AbortError");
    return normalizedVector(result.vector);
  }

  function rank(query, queryVector) {
    const items = photos.filter(photo => vectors.has(photo.id)).map(photo => {
      const vector = vectors.get(photo.id);
      let score = 0;
      for (let i = 0; i < queryVector.length; i += 1) score += queryVector[i] * vector[i];
      return { ...photo, score: Math.max(-1, Math.min(1, score)) };
    });
    if (!window.NebiusRetrieval) throw new Error("Search could not load. Please reload the page.");
    return window.NebiusRetrieval.rankResults(query, items, { semanticThreshold: .25, limit: MAX_PHOTOS });
  }

  function rerank() {
    if (lastSearch && connection && connection.ready) {
      lastSearch.result = rank(lastSearch.query, lastSearch.vector);
    }
    renderCollection();
  }

  async function search(query = $("query").value.trim()) {
    query = query.trim();
    cancelCreationIntent();
    if (!query) { clearSearch(); return; }
    if (!connection || !connection.ready) {
      pendingQuery = query;
      openConnect();
      return;
    }
    const epoch = connectionEpoch;
    const currentSearch = ++searchEpoch;
    const config = connection;
    searching = true;
    notice("Searching your photos…");
    updateControls();
    try {
      const vector = await embed("text", query, config, epoch);
      if (currentSearch !== searchEpoch || epoch !== connectionEpoch) return;
      lastSearch = { query, vector, result: rank(query, vector) };
      pendingQuery = "";
      if (draft) { draft = null; $("prompt-review").hidden = true; }
      $("search-details").open = false;
      renderCollection();
      notice("");
      $("photo-collection").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      if (currentSearch === searchEpoch && epoch === connectionEpoch) notice(error.name === "AbortError" ? "The search took too long. Your Endpoint may be busy; try again when it’s ready." : error.message, true);
    } finally {
      if (currentSearch === searchEpoch) searching = false;
      updateControls();
    }
  }

  function clearSearch() {
    cancelCreationIntent();
    ++searchEpoch;
    searching = false;
    lastSearch = null;
    pendingQuery = "";
    $("query").value = "";
    notice("");
    renderCollection();
  }

  function openConnect(creation = null) {
    cancelCreationIntent();
    pendingCreation = creation;
    const dialog = $("connect-dialog");
    if (connection) {
      $("embedding-url").value = connection.embedding_url;
      $("endpoint-token").value = connection.token;
    }
    $("connect-error").hidden = true;
    if (!dialog.open) dialog.showModal();
    $("embedding-url").focus();
  }

  function resetConnectionForm() {
    for (const id of ["embedding-url", "endpoint-token"]) $(id).value = "";
  }

  function closeConnect() {
    pendingCreation = null;
    if (connecting) disconnect(false);
    $("connect-dialog").close();
    resetConnectionForm();
  }

  function disconnect(showMessage = true) {
    cancelCreationIntent();
    ++connectionEpoch;
    ++searchEpoch;
    abortRequests();
    if (connection) { connection.token = ""; connection.generation_token = ""; }
    connection = null;
    vectors.clear();
    connecting = false;
    indexing = false;
    searching = false;
    lastSearch = null;
    draft = null;
    $("prompt-review").hidden = true;
    $("index-progress").hidden = true;
    $("connect-status").hidden = true;
    $("submit-connect").disabled = false;
    resetConnectionForm();
    renderCollection();
    if (preview) renderPreview();
    if (showMessage) notice("Disconnected. Your photos stay on this device. Your Nebius Endpoint keeps running.");
  }

  async function connect(event) {
    event.preventDefault();
    if (connecting || indexing || !initialized || !$("connect-form").reportValidity()) return;
    // Changing search settings must retain a separately verified creation connection.
    const candidate = { embedding_url: $("embedding-url").value.trim(), token: $("endpoint-token").value.trim(), generation_url: connection && connection.generation_url || "", generation_token: connection && connection.generation_url ? connection.generation_token || connection.token : "", ready: false };
    const epoch = ++connectionEpoch;
    ++searchEpoch;
    abortRequests(["embed", "connect"]);
    if (connection) { connection.token = ""; connection.generation_token = ""; }
    connection = null;
    vectors.clear();
    lastSearch = null;
    connecting = true;
    searching = false;
    $("connect-error").hidden = true;
    $("connect-status").hidden = false;
    $("connect-status-text").textContent = candidate.generation_url ? "Checking search and image creation…" : "Checking photo search…";
    $("submit-connect").disabled = true;
    updateControls();
    try {
      const result = await api("/api/connect", { embedding_url: candidate.embedding_url, token: candidate.token, generation_url: candidate.generation_url, generation_token: candidate.generation_token }, "connect");
      if (epoch !== connectionEpoch) return;
      if (result.dimensions !== DIMENSIONS || typeof result.embedding_model !== "string" || candidate.generation_url && !result.generation_model) throw new Error("The Endpoint models could not be verified.");
      connection = { ...candidate, embedding_model: result.embedding_model, generation_model: result.generation_model || null };
      connecting = false;
      indexing = true;
      $("connect-dialog").close();
      resetConnectionForm();
      showIndexProgress(0, photos.length);
      updateControls();
      for (let i = 0; i < photos.length; i += 1) {
        const photo = photos[i];
        if (!safeImage(photo.data_url)) throw new Error("A photo could not be prepared for indexing. Reload the page and try again.");
        const vector = await embed("image", photo.data_url, connection, epoch);
        if (epoch !== connectionEpoch) return;
        vectors.set(photo.id, vector);
        showIndexProgress(i + 1, photos.length);
      }
      connection.ready = true;
      indexing = false;
      $("index-progress").hidden = true;
      renderCollection();
      if (preview) renderPreview();
      notice(`Ready. ${photos.length} photos are searchable with your Endpoint.`);
      const query = pendingQuery;
      const creation = pendingCreation;
      pendingCreation = null;
      if (creation) startCreation(creation.query, creation.text, creation.options);
      else if (query) await search(query);
    } catch (error) {
      if (epoch !== connectionEpoch) return;
      if (connection) { connection.token = ""; connection.generation_token = ""; }
      connection = null;
      vectors.clear();
      const message = error.name === "AbortError" ? "Your Endpoint took too long to respond. Check that it is running, then connect again." : error.message;
      if ($("connect-dialog").open) { $("connect-error").textContent = message; $("connect-error").hidden = false; }
      else notice(`Indexing didn’t finish. ${message} Connect again to retry.`, true);
    } finally {
      if (epoch === connectionEpoch) {
        connecting = false;
        indexing = false;
        $("connect-status").hidden = true;
        $("submit-connect").disabled = false;
        $("index-progress").hidden = true;
        renderCollection();
      }
    }
  }

  function openDatabase() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open("nebius-photo-search-v1", 1);
      request.onupgradeneeded = () => request.result.createObjectStore("photos", { keyPath: "id" });
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error("Photo storage is blocked."));
    });
  }

  function readPhotos() {
    return new Promise((resolve, reject) => {
      const request = database.transaction("photos", "readonly").objectStore("photos").getAll();
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async function persistPhoto(photo) {
    if (!database) { storageWarning(); return false; }
    // Only media and its descriptive metadata belong in browser storage.
    const record = { id: photo.id, title: photo.title, source_name: photo.source_name, data_url: photo.data_url, example: Boolean(photo.example), generated: Boolean(photo.generated), prompt: photo.prompt || "", created_at: photo.created_at || new Date().toISOString() };
    try {
      await new Promise((resolve, reject) => {
        const transaction = database.transaction("photos", "readwrite");
        transaction.objectStore("photos").put(record);
        transaction.oncomplete = resolve;
        transaction.onerror = () => reject(transaction.error);
        transaction.onabort = () => reject(transaction.error);
      });
      return true;
    } catch (_) { storageWarning(); return false; }
  }

  function blobDataURL(blob) {
    return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error("This photo could not be read.")); reader.readAsDataURL(blob); });
  }

  async function compressPhoto(source) {
    const objectURL = source instanceof Blob ? URL.createObjectURL(source) : null;
    try {
      const image = await new Promise((resolve, reject) => {
        const value = new Image();
        value.onload = () => resolve(value);
        value.onerror = () => reject(new Error("This photo could not be opened. Choose a JPEG, PNG, or WebP image."));
        value.src = objectURL || source;
      });
      if (!image.naturalWidth || !image.naturalHeight || image.naturalWidth * image.naturalHeight > 100000000) throw new Error("This image is too large. Choose an image smaller than 100 megapixels.");
      const scale = Math.min(1, 1024 / Math.max(image.naturalWidth, image.naturalHeight));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
      const context = canvas.getContext("2d", { alpha: false });
      if (!context) throw new Error("Your browser could not prepare this image.");
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      const data = canvas.toDataURL("image/jpeg", .86);
      if (!safeImage(data) || data.length > 2.7 * 1024 * 1024) throw new Error("This photo is still too large to index. Please choose a smaller image.");
      return data;
    } finally { if (objectURL) URL.revokeObjectURL(objectURL); }
  }

  async function initialize() {
    renderCollection();
    try { database = await openDatabase(); } catch (_) { storageWarning(); }
    let stored = [];
    if (database) {
      try { stored = await readPhotos(); }
      catch (_) { database = null; storageWarning(); }
    }
    try {
      const valid = stored.filter(photo => photo && typeof photo.id === "string" && typeof photo.title === "string" && safeImage(photo.data_url)).slice(0, MAX_PHOTOS);
      if (valid.length) photos = valid;
      else {
        photos = await Promise.all(SEEDS.map(async seed => {
          const response = await fetch(`/examples/${seed.source_name}`, { credentials: "same-origin" });
          if (!response.ok) throw new Error("The example photos could not be loaded. Reload to try again.");
          const data_url = await blobDataURL(await response.blob());
          return { ...seed, data_url, example: true, generated: false, created_at: new Date().toISOString() };
        }));
        for (const photo of photos) await persistPhoto(photo);
      }
    } catch (error) { notice(error.message || "The collection could not be loaded. Please reload the page.", true); }
    initialized = photos.every(photo => safeImage(photo.data_url));
    renderCollection();
  }

  async function addPhotos(files) {
    if (!files.length || uploading || indexing || connecting || preview && preview.saving) return;
    if (files.length + photos.length > MAX_PHOTOS) { notice(`This demo holds up to ${MAX_PHOTOS} photos. You can add ${MAX_PHOTOS - photos.length} more.`, true); return; }
    if (files.some(file => !["image/jpeg", "image/png", "image/webp"].includes(file.type) || file.size > 20 * 1024 * 1024)) { notice("Choose JPEG, PNG, or WebP photos smaller than 20 MB each.", true); return; }
    const epoch = connectionEpoch;
    const config = connection && connection.ready ? connection : null;
    uploading = true;
    let added = 0;
    updateControls();
    notice("");
    if (config) showIndexProgress(0, files.length, "Adding your photos");
    try {
      for (const file of files) {
        const data_url = await compressPhoto(file);
        if (photos.some(photo => photo.data_url === data_url)) continue;
        const photo = { id: crypto.randomUUID(), title: file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "), source_name: file.name, data_url, example: false, generated: false, created_at: new Date().toISOString() };
        const vector = config ? await embed("image", data_url, config, epoch) : null;
        if (epoch !== connectionEpoch) throw new DOMException("Connection changed", "AbortError");
        if (photos.length >= MAX_PHOTOS) throw new Error(`Your collection is full. This demo supports up to ${MAX_PHOTOS} photos.`);
        await persistPhoto(photo);
        photos.push(photo);
        added += 1;
        if (epoch !== connectionEpoch) throw new DOMException("Connection changed", "AbortError");
        if (vector) vectors.set(photo.id, vector);
        if (config) showIndexProgress(added, files.length, "Adding your photos");
      }
      notice(added ? `Added ${added} ${added === 1 ? "photo" : "photos"}. ${config ? "Ready to search." : "Connect your Endpoint to make them searchable."}` : "Those photos are already in your collection.");
    } catch (error) { notice(error.name === "AbortError" ? "Adding photos stopped because the connection changed. Photos already added are safe." : error.message, true); }
    finally { uploading = false; $("index-progress").hidden = true; $("photo-input").value = ""; rerank(); }
  }

  function generationStatus(title, description, { busy = false, error = false, action = null, label = "Review prompt" } = {}) {
    $("generation-status").hidden = false;
    $("generation-status").classList.toggle("error", error);
    $("generation-title").textContent = title;
    $("generation-description").textContent = description;
    $("generation-spinner").hidden = !busy;
    generationAction = action;
    $("generation-action").hidden = !action;
    $("generation-action").textContent = label;
  }

  function cancelCreationIntent() {
    ++generationConnectEpoch;
    abortRequests(["connect-generation"]);
    generationIntent = null;
    pendingCreation = null;
    generationConnecting = false;
    draft = null;
    $("prompt-review").hidden = true;
    $("generation-dialog").close();
    $("flux-url").value = "";
    $("flux-token").value = "";
    $("generation-connect-error").hidden = true;
    $("generation-connect-status").hidden = true;
    if (!generationBusy && !(preview && !preview.saved)) {
      $("generation-status").hidden = true;
      generationAction = null;
    }
  }

  function startCreation(query = lastSearch && lastSearch.query, text = query, options = {}) {
    if (!query || searching || generationBusy || preview && !preview.saved || connecting || indexing || uploading || !initialized) return;
    if (!connection || !connection.ready) {
      pendingQuery = "";
      openConnect({ query, text, options });
      return;
    }
    cancelCreationIntent();
    generationIntent = { query, text, options, search: searchEpoch, connection: connectionEpoch };
    if (connection.generation_url) { reviewPrompt(query, text, options); return; }
    $("generation-connect-description").textContent = `Add your FLUX Endpoint to create an image of “${query}”. You’ll review the prompt before anything is generated.`;
    $("flux-token-options").open = false;
    $("generation-dialog").showModal();
    $("flux-url").focus();
    updateControls();
  }

  function createFromDescription() {
    const query = $("query").value.trim();
    if (!query) {
      notice("Describe the image you want to create in the box above, then choose Create an image.");
      $("query").focus();
      return;
    }
    startCreation(query);
  }

  function closeGenerationConnect() {
    cancelCreationIntent();
    updateControls();
  }

  async function connectGeneration(event) {
    event.preventDefault();
    if (generationConnecting || !generationIntent || !connection || !connection.ready || !$("generation-connect-form").reportValidity()) return;
    const intent = generationIntent;
    const config = connection;
    const epoch = ++generationConnectEpoch;
    const separateToken = $("flux-token").value.trim();
    const generationURL = $("flux-url").value.trim();
    generationConnecting = true;
    $("generation-connect-error").hidden = true;
    $("generation-connect-status").hidden = false;
    updateControls();
    try {
      const result = await api("/api/connect-generation", { generation_url: generationURL, token: separateToken || config.token }, "connect-generation");
      if (epoch !== generationConnectEpoch || intent !== generationIntent || config !== connection || intent.search !== searchEpoch || intent.connection !== connectionEpoch) return;
      if (typeof result.generation_url !== "string" || typeof result.generation_model !== "string") throw new Error("The FLUX Endpoint could not be verified.");
      config.generation_url = result.generation_url;
      config.generation_token = separateToken;
      config.generation_model = result.generation_model;
      $("generation-dialog").close();
      $("flux-url").value = "";
      $("flux-token").value = "";
      reviewPrompt(intent.query, intent.text, intent.options);
    } catch (error) {
      if (epoch !== generationConnectEpoch || intent !== generationIntent) return;
      $("generation-connect-error").textContent = error.name === "AbortError" ? "The FLUX Endpoint took too long. Check that it is running, then try again." : error.message;
      $("generation-connect-error").hidden = false;
    } finally {
      if (epoch === generationConnectEpoch) {
        generationConnecting = false;
        $("generation-connect-status").hidden = true;
        updateControls();
      }
    }
  }

  function initialPromptDraft(text) {
    const words = text.trim().split(/\s+/);
    // A short subject benefits from a visible image brief. Respect sentences,
    // explicit visual briefs, and all text that the user has already approved.
    const visualBrief = /\b(?:photo(?:graph)?|illustration|portrait|painting|render|drawing|sketch)\b/i.test(text) && words.length > 1;
    const isSubject = words.length <= 4 && !/[.!?;:\n]/.test(text) && !visualBrief && !/^(?:create|generate|draw|make|show)\b/i.test(text);
    return isSubject
      ? { text: `A high-quality stock photograph of ${text}, with a clearly visible main subject and natural lighting. Use generic equipment and original designs.`, drafted: true }
      : { text, drafted: false };
  }

  function reviewPrompt(query = lastSearch && lastSearch.query, text = query, options = {}) {
    if (!query || generationBusy || preview && !preview.saved) return;
    if (!connection || !connection.ready || !connection.generation_url) { startCreation(query, text, options); return; }
    generationIntent = null;
    draft = { query, request_id: crypto.randomUUID() };
    const prepared = options.preserve ? { text, drafted: false } : initialPromptDraft(text);
    $("generation-prompt").value = prepared.text;
    $("prompt-draft-note").hidden = !prepared.drafted;
    $("generation-warning").hidden = !generationAmbiguous;
    $("prompt-review").hidden = false;
    $("generation-status").hidden = true;
    $("generated-preview").hidden = true;
    updateControls();
    $("generation-prompt").focus();
    $("prompt-review").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderPreview() {
    if (!preview) return;
    $("generated-preview").hidden = false;
    $("preview-image").src = preview.data_url;
    $("preview-image").alt = `AI-generated image: ${preview.prompt.slice(0, 250)}`;
    $("preview-prompt").textContent = preview.prompt;
    $("preview-kicker").textContent = preview.saved ? "ADDED TO YOUR COLLECTION" : "STEP 2 · KEEP IT OR DISCARD IT";
    $("preview-image-badge").textContent = preview.saved ? "AI-GENERATED" : "AI-GENERATED PREVIEW";
    const searchable = preview.saved && preview.photo && connection && connection.ready && vectors.has(preview.photo.id);
    $("preview-title").textContent = preview.saved ? searchable ? "Saved and ready to search." : "Saved to your collection." : "Add this image to your collection?";
    $("preview-description").textContent = preview.saved
      ? searchable
        ? preview.persisted ? "This image is saved on this device and is now searchable with your collection." : "This image is searchable in this tab. Browser storage is unavailable, so keep this tab open."
        : preview.persisted ? "This image is saved on this device. Reconnect to make it searchable." : "This image is kept in this tab. Reconnect to make it searchable, and keep this tab open."
      : "This preview is only in this tab. Save it to make it searchable in your collection.";
    $("preview-actions").hidden = Boolean(preview.saved);
    updateControls();
  }

  async function generate() {
    if (!draft || generationBusy || !connection || !connection.ready || !connection.generation_url) return;
    const prompt = $("generation-prompt").value.trim();
    if (!prompt) return;
    const approved = { ...draft, prompt };
    const config = connection;
    draft = null;
    generationBusy = true;
    $("prompt-review").hidden = true;
    $("generated-preview").hidden = true;
    updateControls();
    generationStatus("Creating your image…", "FLUX is working on your approved prompt. You can keep searching while you wait. Nothing is saved yet.", { busy: true });
    try {
      const result = await api("/api/generate", { base_url: config.generation_url, token: config.generation_token || config.token, prompt, approved: true, request_id: approved.request_id }, "generate", 15 * 60 * 1000);
      if (!safeImage(result.image_data_url)) throw new Error("The image response could not be opened.");
      preview = { data_url: result.image_data_url, prompt, query: approved.query, request_id: approved.request_id, model: result.model, saved: false, saving: false, photo: null };
      generationAmbiguous = false;
      $("generation-status").hidden = true;
      renderPreview();
      $("generated-preview").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      const preflight = new Set(["invalid_url", "invalid_token", "approval_required", "wrongmodel", "wrong_model", "request_limit", "gpu_busy"]).has(error.code);
      generationAmbiguous = !preflight && (!Number.isInteger(error.status) || error.status >= 500 || [408, 409, 499].includes(error.status));
      const title = error.code === "model_declined" ? "FLUX didn’t return an image."
        : error.code === "model_request_invalid" ? "The image service rejected the request."
        : preflight ? "The image request wasn’t started." : generationAmbiguous ? "We couldn’t confirm the image result." : "The image request couldn’t be completed.";
      generationStatus(title, generationAmbiguous ? "The request may still be running or its image may no longer be available. Starting again could create another image." : error.message, { error: true, action: () => reviewPrompt(approved.query, approved.prompt, { preserve: true }), label: "Review prompt" });
    } finally { generationBusy = false; updateControls(); }
  }

  async function savePreview() {
    const current = preview;
    if (!current || current.saved || current.saving || uploading || indexing || connecting) return;
    if (!connection || !connection.ready) { openConnect(); return; }
    if (photos.length >= MAX_PHOTOS) { notice(`Your collection is full. This demo supports up to ${MAX_PHOTOS} photos.`, true); return; }
    const epoch = connectionEpoch;
    const config = connection;
    current.saving = true;
    updateControls();
    generationStatus("Adding the image to your collection…", "Making this image searchable with your Qwen3-VL Endpoint.", { busy: true });
    try {
      if (!current.photo) current.photo = { id: `generated-${current.request_id}`, title: current.prompt, source_name: "generated-image.jpg", prompt: current.prompt, data_url: await compressPhoto(current.data_url), example: false, generated: true, created_at: new Date().toISOString() };
      const vector = await embed("image", current.photo.data_url, config, epoch);
      if (preview !== current || epoch !== connectionEpoch) return;
      if (photos.length >= MAX_PHOTOS && !photos.some(photo => photo.id === current.photo.id)) throw new Error(`Your collection is full. This demo supports up to ${MAX_PHOTOS} photos.`);
      current.persisted = await persistPhoto(current.photo);
      if (!photos.some(photo => photo.id === current.photo.id)) photos.push(current.photo);
      current.saved = true;
      $("generation-status").hidden = true;
      if (preview !== current || epoch !== connectionEpoch) {
        if (preview === current) renderPreview();
        rerank();
        return;
      }
      vectors.set(current.photo.id, vector);
      renderPreview();
      rerank();
    } catch (error) {
      generationStatus("The image hasn’t been added yet.", error.name === "AbortError" ? "The connection changed. Reconnect, then add this same preview again." : error.message, { error: true, action: savePreview, label: "Try saving again" });
    } finally { current.saving = false; updateControls(); }
  }

  function discardPreview() {
    if (!preview || preview.saving || preview.saved) return;
    preview = null;
    $("preview-image").removeAttribute("src");
    $("generated-preview").hidden = true;
    generationStatus("Preview discarded.", "No image was added to your collection.");
    updateControls();
  }

  $("search-form").addEventListener("submit", event => { event.preventDefault(); search(); });
  $("query").addEventListener("search", () => { if (!$("query").value.trim()) clearSearch(); });
  $("clear-search").addEventListener("click", clearSearch);
  document.querySelectorAll("[data-query]").forEach(button => button.addEventListener("click", () => { $("query").value = button.dataset.query; search(button.dataset.query); }));
  $("connect-button").addEventListener("click", () => openConnect());
  $("disconnect-button").addEventListener("click", () => disconnect());
  $("connect-form").addEventListener("submit", connect);
  $("close-connect").addEventListener("click", closeConnect);
  $("cancel-connect").addEventListener("click", closeConnect);
  $("connect-dialog").addEventListener("cancel", event => { event.preventDefault(); closeConnect(); });
  $("add-photos").addEventListener("click", () => $("photo-input").click());
  $("photo-input").addEventListener("change", event => addPhotos(Array.from(event.target.files || [])));
  $("create-from-description").addEventListener("click", createFromDescription);
  $("create-image").addEventListener("click", () => startCreation());
  $("empty-create-yes").addEventListener("click", () => startCreation());
  $("empty-create-no").addEventListener("click", () => {
    cancelCreationIntent();
    creationDeclinedSearch = searchEpoch;
    updateControls();
    $("query").focus();
    $("search-form").scrollIntoView({ behavior: "smooth", block: "center" });
  });
  $("generation-connect-form").addEventListener("submit", connectGeneration);
  $("close-generation-connect").addEventListener("click", closeGenerationConnect);
  $("cancel-generation-connect").addEventListener("click", closeGenerationConnect);
  $("generation-dialog").addEventListener("cancel", event => { event.preventDefault(); closeGenerationConnect(); });
  $("generation-prompt").addEventListener("input", updateControls);
  $("cancel-generation").addEventListener("click", () => { cancelCreationIntent(); updateControls(); });
  $("approve-generation").addEventListener("click", generate);
  $("generation-action").addEventListener("click", () => { if (generationAction) generationAction(); });
  $("save-image").addEventListener("click", savePreview);
  $("discard-image").addEventListener("click", discardPreview);
  initialize();
})();
