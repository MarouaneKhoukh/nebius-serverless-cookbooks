# Preview provenance

## Core Search + Create interface: 2 November 2026

`search-create-core.png` is an unmodified browser screenshot of the revised **Search + Create** interface, with the authentic logo, exact **Powered by Nebius Serverless AI** label, a primary creation action and both model connections ready. A real coffee search returned Coffee beans and the saved barista image. `search-create-partial-setup.png` captures the earlier stage after collection/search connection and before FLUX was connected; its hint asks the reader to complete setup through Create.

The browser chose Create before any connection, retained its teapot description through collection indexing and FLUX verification, reached editable review and cancelled it. No new image was generated or added. These are current interface/connection checks; the earlier actual generation footage below records a separate run. [Browser observations](../evidence/core-search-create-2026-11-02.json).

## Create-first connection flow: 2 November 2026

These are unmodified browser screenshots from the updated Node app and the same five-photo collection:

- `create-choice.png`: the football no-match screen asks whether to create, before generation is connected.
- `connect-flux-after-choice.png`: choosing yes opens the focused FLUX URL form; no token is displayed and no model generation has started.
- `review-after-connection.png`: the real H200 model check succeeded and opened the editable **football** prompt with **Approve and generate**.
- `create-choice-final.png`: after cancelling review, the no-match question is visible again; both APIs are connected and the collection still contains five photos.

The live check also exercised No, cancelled connection, and a second yes that skipped the already-completed connection step. No generation was approved or attempted, no photos were added or removed, and the Endpoint was not changed. [Recorded observations](../evidence/creation-journey-2026-11-02.json). These current screenshots refine the connection sequence; the earlier generation/saving walkthrough below remains evidence of that earlier live run.

## Search relevance correction: 2 November 2026

`search-football-no-match.png` and `search-espresso-match.png` are unmodified browser screenshots of the updated app, connected to the existing H200 embedding Endpoint and its five-image browser collection. Football shows **No matching photos** with zero result cards. Espresso shows the saved robot barista and Coffee beans; the beans qualify through visual similarity rather than a name match. No generation occurred for these checks, no photos were added or removed, and no token is visible. These captures document the corrected accepted-only gallery and sample-informed 0.25 cutoff. The connection/generation walkthrough below predates this filtering correction; its approval and saving flow is unchanged. See the [relevance evaluation](../evidence/search-relevance-2026-11-02.json) and [validation record](../../VALIDATION.md).

## Current live browser-connected walkthrough: 2 November 2026

The main README now uses these actual captures of the Node-hosted browser-connected app:

- `byo-endpoint-live.jpg`: the unmodified **898×853** JPEG of the final **Matches for “coffee”** result, with **Coffee beans**, the authentic Nebius logo and **Powered by Nebius Serverless AI** visible. It is a byte-for-byte copy of the browser capture.
- `byo-endpoint-live.mp4`: a **24-second** H.264 screenshot walkthrough at **898×854**, 8 fps. Only a single white bottom row is added for the encoder's even-height requirement; browser content is not resized.
- `byo-endpoint-live.gif`: the same sequence at its natural **898×853** size, 6 fps.

| Screenshot | Hold | What it actually shows |
| --- | --- | --- |
| Connection form | 3 seconds | The real form, revisited with empty token fields; credential entry is omitted |
| Coffee results | 3 seconds | Coffee beans appears as a name match in the connected app |
| Edited prompt | 4 seconds | The reviewed robot-barista description and **Approve and generate** |
| Generation progress | 2 seconds | The real in-progress operation |
| Saved result | 4 seconds | The saved robot-barista result after explicit Add |
| Subsequent retrieval | 3 seconds | A **robot barista** search retrieves the saved image first |
| Separate unsaved preview | 3 seconds | A second generation, the violet glass pineapple, with **Add to collection** and **Discard** |
| Final coffee search | 2 seconds | Coffee beans still matches; the collection contains five photos |

This is a montage of real browser screenshots with pauses shortened, **not continuous screen recording or a generation-latency benchmark**. The empty connection form was revisited for a credential-free capture; the video does not show a token being entered. The pineapple preview belongs to a separate generation after the robot was saved, not an alternate result from the robot prompt. The capture shows the pineapple before Discard; the discarded outcome was verified in the browser and final collection count, not filmed as an uninterrupted click sequence.

The local app called real **Qwen3-VL-Embedding-8B** and **FLUX 3 Image Klein** APIs through its Node proxy on one running **H200** Endpoint. The initial three starter photos were indexed and the pending coffee search resumed after connection. A visual mountain query also returned its matching photo. A real API-generated rubber-duck image was then added through the browser file chooser, taking the collection from **three to four**; that upload is outside this montage.

The robot prompt was reviewed as:

> A small teal robot barista pouring espresso into a white ceramic cup in a warm wood-paneled cafe, natural window light, realistic photograph.

The resulting preview remained unsaved at **four photos**. Explicit **Add to collection** embedded it and changed the count to **five**. A later **robot barista** search retrieved it first. A second browser generation used:

> A violet glass pineapple on a clean white studio table, soft shadows, product photograph.

Its preview was explicitly discarded, and the collection remained at **five**. Reloading and reconnecting preserved all five saved photos, re-indexed them, and the final **coffee** search still returned Coffee beans. No Endpoint token is present in the captures. These are successful local browser/inference checks, not evidence of a published HTTPS Site, a continuous video of every step, or GPU startup from the separately published custom image. [Current validation](../../VALIDATION.md) records the evidence and remaining limits.

The browser-to-Node hop is HTTP on loopback only; Node-to-Nebius uses HTTPS. A hosted deployment must use HTTPS for both hops. Public Endpoint URLs visible in the connection form are not credentials; readers must connect their own Endpoint. [Logo provenance](../../media_search/static/brand/SOURCE.md).

The starter photos are by [Negative Space](https://www.pexels.com/photo/beans-coffee-cup-mug-34079/) (coffee), [eberhard grossgasteiger](https://www.pexels.com/photo/landscape-photo-of-snowy-mountains-near-lake-1292677/) (mountains) and [Robert Stokoe](https://www.pexels.com/photo/city-buildings-at-night-9097693/) (city). Their [source, file and license details](../../examples/SOURCES.md) are included with the cookbook.

## Earlier connection-only preview: 2 November 2026

This shorter connection-only preview is retained as an optional README link:

- `connect-endpoint-preview.jpg`: the unmodified **898×853** JPEG of the connection form. It is a byte-for-byte copy of the original browser capture.
- `connect-endpoint-preview.mp4`: an **8-second** H.264 screenshot walkthrough at **898×854**, 8 fps. A single white row pads the bottom for the encoder's even-height requirement; browser content is not resized.
- `connect-endpoint-preview.gif`: the same two screenshots at their natural **898×853** size, 6 fps.

The sequence holds the starter gallery for **4 seconds**, then the Endpoint connection form for **4 seconds**. Searching while disconnected opened the form. The embedding and generation public URLs were entered, but **no Endpoint token was entered and no browser connection was submitted**. The capture shows connection setup only. It does not show completed browser indexing, search, generation, saving or a published site.

This is an assembled screenshot walkthrough, not continuous screen recording, a latency benchmark or a simulated successful connection. Both screenshots show the real application; no generated frames, fixture model responses or fabricated result screens were added. The local browser-to-proxy hop uses HTTP on loopback only; the proxy-to-Nebius hop uses HTTPS. A hosted deployment must use HTTPS for both hops.

Separate API checks through the same Node proxy used the real running H200 Endpoint: **coffee**, **a lake in the mountains** and **a city after dark** each ranked the intended starter photo first. A wrong token returned HTTP 401. Nine embedding requests and one 1024×1024 FLUX generation succeeded; the measured generation request took **11.4 seconds**. Those are API checks, not interactions filmed in this connection-only preview. The later complete browser run is documented above; neither local run establishes successful public hosting. See the [validation record](../../VALIDATION.md) for the current evidence and remaining limits.

The first screenshot displays the authentic Nebius logo and exact **Powered by Nebius Serverless AI** label. The second displays the real connection form; its token fields are empty. Public Endpoint URLs are not credentials, but readers must supply URLs and a token for their own Endpoint. [Logo provenance](../../media_search/static/brand/SOURCE.md).

The starter photos visible behind the form and in the gallery are by [Negative Space](https://www.pexels.com/photo/beans-coffee-cup-mug-34079/) (coffee), [eberhard grossgasteiger](https://www.pexels.com/photo/landscape-photo-of-snowy-mountains-near-lake-1292677/) (mountains) and [Robert Stokoe](https://www.pexels.com/photo/city-buildings-at-night-9097693/) (city). Their [source, file and license details](../../examples/SOURCES.md) are included with the cookbook.

## Earlier Python prompt-approval and image-review walkthrough: 2 November 2026

These historical Python-app captures are linked separately in the README:

- `search-create-live.jpg`: the unmodified 898×853 JPEG capture of the private, unsaved generated-image preview, with **Add to collection** and **Discard** visible.
- `search-create-live.mp4`: an 18-second H.264 screenshot walkthrough, 898×854 pixels at 8 fps. One white pixel row is added at the bottom because H.264 requires an even height; the browser content is not resized.
- `search-create-live.gif`: the same five-capture sequence at 898×853 pixels and 6 fps, without padding.

The sequence holds the reviewed prompt for 4 seconds, generation progress for 2 seconds, the unsaved preview for 5 seconds, the saved result for 3 seconds, and later retrieval for 4 seconds. It assembles real screenshots and shortens waiting periods. **It is not a continuous screen recording or a claim about generation speed.** No fixture responses, fabricated UI, generated recording frames or simulated results are used.

The local gallery called the real Qwen3-VL Embedding and FLUX 3 Image Klein APIs on one **H200** Endpoint, `REDACTED_H200_ENDPOINT_ID`, in the user's selected project. The GPU runtime used the public vLLM base with the cookbook Endpoint sources and frozen generation dependencies bootstrapped at startup. This records a live inference run; it does not establish direct GPU startup from the published custom image or public HTTPS hosting. See [validation](../../VALIDATION.md) for deployment evidence and scope.

The search description was **“a ceramic teapot shaped like a sleepy dragon”**. Before approval, its proposed prompt was edited to:

> A jade-green ceramic teapot shaped like a sleepy dragon, curled tail handle, on a wooden tea tray beside a small white cup, soft morning window light, product photograph.

Generation began only after **Approve and generate**. The collection contained **eight images** when the private preview became ready, and no image embedding had occurred for that preview. The preview required its owning browser session; a request without a session returned HTTP 403 and another session received HTTP 404. After **Add to collection**, the image was embedded and indexed, the collection contained **nine images**, and a later search retrieved it first with cosine similarity approximately **0.527**. Similarity is not a confidence percentage. The capture shows the save path; it does not visually demonstrate a separate Discard operation.

The authentic Nebius SVG and the exact **Powered by Nebius Serverless AI** label remain visible. [Logo provenance](../../media_search/static/brand/SOURCE.md). The supplied-photo credits and license links are in [example sources](../../examples/SOURCES.md).

The prior captures below are retained under historical filenames so their older interaction flow is not confused with this walkthrough.

## Historical RTX walkthrough with automatic saving: 2 November 2026

Archived artifacts from the earlier automatic-generation/automatic-save interface:

- `search-create-rtx-autosave.jpg`: unaltered full-page browser screenshot of the actual second FLUX-generated result.
- `search-create-rtx-autosave.mp4`: 24-second H.264 walkthrough assembled from real browser screenshots, with waiting periods shortened; 602×854 pixels, including a one-pixel outer padding needed by the encoder.
- `search-create-rtx-autosave.gif`: the same screenshot sequence at 601×853 pixels.

The local gallery called the real Qwen3-VL Embedding and FLUX 3 Image Klein APIs on one Nebius RTX PRO 6000 Blackwell Endpoint. The live runtime used the public vLLM base with the cookbook Endpoint sources injected and its frozen generation dependencies bootstrapped at startup; see [validation](../../VALIDATION.md) for the packaging distinction. No fixture responses or fabricated UI/results were used in this walkthrough.

The captured sequence is: the initial four-image gallery (three bundled Pexels photos and the first generated robot), a successful mountain-photo search, a no-match description **“a glass chess set floating inside a soap bubble in outer space”**, the real generation progress, the resulting AI-generated card, and a later search retrieving that same image. Its output is labelled **AI-generated** in the gallery.

Two real 1024×1024 generations occurred during this GPU session: the first in the acceptance harness, the second through the recorded browser flow. The animation is a concise screenshot walkthrough, **not a continuous frame-rate screen recording and not a latency benchmark**. Actual operation durations and sampled GPU memory are recorded separately in the validation evidence.

The authentic Nebius SVG and the exact **Powered by Nebius Serverless AI** label are visible in the demo. [Logo provenance](../../media_search/static/brand/SOURCE.md). The included-photo credits and license links are in [example sources](../../examples/SOURCES.md).

This RTX walkthrough, the offline preview and the search-only recording below are historical evidence. They do not demonstrate the current prompt-approval and explicit-save interface.

## Historical offline search-and-create preview: 2 November 2026

`search-create-preview.jpg` is an unaltered full-page browser screenshot of the real gallery and API running locally with injected offline embedding/generation fixtures and in-memory Qdrant. The page has a prominent banner stating **Offline UI preview — fixture responses; no Qwen or FLUX inference**. Its illustrations are drawn, labelled test inputs; the result is not a FLUX-generated image.

The browser exercised no-match search, queued image creation, indexing, AI-generated result display, retrieval on the next search and video-only exclusion. This capture documents interface behavior, not generation quality, semantic retrieval, model performance or a GPU run. The fixture harness is authoring tooling outside the runnable cookbook.

The original search-only recording below is retained as historical evidence.

## Search-only recording: 29 October 2026

Captured from the running local gallery on 29 October 2026 using browser screenshots: library view (3 seconds), photo filter (3 seconds), then actual native video playback (6 seconds). Frames were assembled into H.264 MP4 at 8 fps and an animated GIF at 6 fps; no search responses or results were fabricated. The poster is an unaltered browser capture converted to PNG.

Sample media consists of synthetic shapes, with five entries previously embedded on the real Nebius GPU endpoint. That endpoint remained stopped during capture. This footage demonstrates browsing, filtering and playback, not a new semantic search or a benchmark. See LIVE-TEST.md at the recipe root for actual search validation.

The logo is the unchanged official SVG; provenance is in ../../media_search/static/brand/SOURCE.md. Captures show the exact label Powered by Nebius Serverless AI.
