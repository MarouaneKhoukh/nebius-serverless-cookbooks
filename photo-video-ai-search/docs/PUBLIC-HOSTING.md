[← Back to the cookbook](../README.md)

# Share the browser-connected demo

Publish `hosted-demo/` so readers can open an HTTPS app, connect their own Nebius Endpoint, and search or create images. The hosted app includes a server proxy; a static file host alone is insufficient.

| Runs where | What it does |
| --- | --- |
| Visitor's browser | Keeps that browser's saved photos in IndexedDB; holds vectors and tokens in memory |
| Web host | Serves the interface and forwards bounded inference requests |
| Visitor's Nebius Endpoint | Runs Qwen, FLUX and the required companion models |

The web app starts disconnected. Publishing it does not publish your Endpoint token or gallery. Each visitor needs the compatible Endpoint described in the [cookbook](../README.md).

## Publish with a Sites agent

Enable the Sites plugin in a compatible agent, open the cookbook directory, and give it this prompt:

```text
Publish this cookbook's hosted-demo as a Sites app. Use the installed Sites
skill and its supported Worker build/source/publication workflow. Read
README.md and hosted-demo's source. Reuse .openai/hosting.json if present;
do not create a duplicate Site.

From the cookbook root, run:
  node --test hosted-demo/tests/*.test.mjs
Then from hosted-demo, run:
  node scripts/build.mjs
Publish the generated Worker through the Sites Worker ESM workflow,
including the frontend, starter photos and same-origin Endpoint proxy.
Do not deploy server.mjs. Preserve the authentic Nebius logo and exact
label "Powered by Nebius Serverless AI".

Never put Endpoint tokens in source, Site environment variables, media,
logs or publication output. Exclude .env, local data and private files.
Start visitors disconnected. Preserve search -> connect -> model checks ->
indexing -> resumed search, reviewed generation approval, unsaved preview,
explicit Add or Discard, and browser-local image persistence.

Set the intended audience using supported Sites access settings. If public
access is unavailable, report that limit. Test the actual deployed HTTPS
origin, then report its URL and audience. Update the cookbook's hosted URL
only after publication succeeds. Do not create, start, stop or modify any
Nebius resources as part of publishing the web app.
```

`server.mjs` is the local Node entrypoint. The build packages the assets into a standalone Worker for hosting. Keep the Site identity in the deployment working copy; exclude its write credentials from downloadable cookbook files.

## Check the published app

Use an already authorized Endpoint and a bounded inference test:

1. Search **coffee** while disconnected. Connect with the port-8000 base URL and Endpoint token; confirm indexing completes and coffee beans appears. A wrong token must show a clear error.
2. Search **espresso**, then **football**. The starter collection should match coffee beans for espresso and show **No matching photos** for football.
3. Choose **Yes, create an image**. Connect the port-8001 URL, review the prompt and cancel. Confirm this has not generated an image or re-indexed the collection.
4. Approve a generation. The preview must remain unsaved until **Add to collection**. Check a saved image is searchable; check Discard only if another generation is within the approved scope.
5. Reload and reconnect. Saved photos should remain, credentials should be requested again, and another browser profile should have a separate collection.

Record actual results in [VALIDATION.md](../VALIDATION.md). A successful upload or local preview does not establish that the hosted URL works for its intended readers.

## Before sharing

- **Trust the host.** It forwards visitor credentials to the selected inference API over HTTPS. Keep request-body logging and connection-field analytics disabled. Preserve the proxy's managed-URL validation, redirect rejection, request limits, timeouts and safe errors.
- **Explain storage.** Photos stay in this browser and origin, with a 20-image cap. They do not sync between devices. Reloading clears credentials and vectors; reconnecting re-embeds saved photos. Unsaved previews disappear on reload.
- **Explain compute.** Each visitor controls and pays for their own Endpoint. Disconnecting or closing the page does not stop it; follow [Stop the GPU](../README.md#6-stop-the-gpu).
- **Check model terms.** Review the operator's applicable [FLUX Kommunity License](https://huggingface.co/black-forest-labs/flux-3-image-klein/blob/main/LICENSE.md) and complete human model-access approval before public use. Retain upstream prompt expansion and content checks. A free demo label alone does not establish eligibility.

For one operator-owned collection with Qdrant and server-side credentials, use the separate [Python + Qdrant guide](QDRANT.md).
