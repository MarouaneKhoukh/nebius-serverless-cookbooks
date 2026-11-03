# Deploy the demo on Vercel

The hosted gallery lets each visitor connect their own running Nebius Endpoint. No GPU, API token, model weights or shared inference credentials are included in the deployment.

1. Import this repository in Vercel, or run `vercel` from this `hosted-demo` folder.
2. Set **Root Directory** to `photo-video-ai-search/hosted-demo`, **Framework** to **Other**, **Build Command** to `npm run build`, and **Output Directory** to `dist`.
3. Use the Node.js runtime with **Fluid Compute enabled**. The included configuration gives the API up to 300 seconds. No environment variables are needed.
4. Deploy. For a link that teammates can open without signing in to your Vercel team, use the production deployment and check its **Deployment Protection** settings.
5. Open the link. The three starter photos appear immediately. Search asks for the visitor's port-8000 public URL and Endpoint token. Choosing image creation then asks for port 8001, followed by prompt approval and an explicit save/discard choice. Follow the [cookbook](../README.md) to prepare the Endpoint.

To deploy from this folder after signing in to Vercel:

```sh
npm test
npm run build
vercel --prod
```

Check `/health` for `{"ok":true}` without sending an inference request. Local use remains `npm start`; the separate Worker build is available as `npm run build:worker`.

## Hosting boundaries

- The page keeps tokens in memory and sends them only to its same-origin relay, which forwards them to the visitor's restricted Nebius managed public URL. It never saves or logs them. Reloading requires reconnecting. Photos stay in that browser's IndexedDB; indexing and generated previews pass through the relay in memory.
- The relay rejects arbitrary hosts, ports, paths, redirects and cross-site requests. Limits remain 3 MiB per request and 2 MiB per prepared photo. On Vercel, upstream generation JSON is capped at 4,000,000 bytes and the PNG at 2,900,000 bytes, so base64 responses fit below the platform's 4.5 MB ceiling. An oversized image returns a clear error; the model may already have finished that attempt.
- Upstream timeouts are 20 seconds for model checks, 90 seconds for embedding and 240 seconds for generation. Keep Fluid Compute enabled for the configured 300-second function duration.
- Rate limits and duplicate-generation guards are **best effort within a warm function instance**. They are not a global quota or durable idempotency service across instances or deployments. The app never automatically retries image generation; a failed response asks the user to review before another attempt. Each visitor pays for their own Endpoint. Consider Vercel Firewall/rate rules for a wider public launch.

Vercel references: [Node.js functions](https://vercel.com/docs/functions/runtimes/node-js), [function limits](https://vercel.com/docs/functions/limitations), [trusted request headers](https://vercel.com/docs/headers/request-headers).
