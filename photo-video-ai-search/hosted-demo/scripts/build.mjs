import { readFile, readdir, mkdir, writeFile } from "node:fs/promises";
import { resolve, relative, extname } from "node:path";
import { fileURLToPath } from "node:url";
export const root = fileURLToPath(new URL("..", import.meta.url));
const types = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".jpg": "image/jpeg", ".png": "image/png", ".md": "text/plain; charset=utf-8" };
export async function assets(directory = resolve(root, "public")) {
  const result = {};
  async function visit(folder) {
    for (const item of await readdir(folder, { withFileTypes: true })) {
      if (item.name.startsWith(".")) continue;
      const path = resolve(folder, item.name);
      if (item.isDirectory()) await visit(path);
      else if (item.isFile()) result["/" + relative(directory, path).split("\\").join("/")] = { type: types[extname(path)] || "application/octet-stream", body: (await readFile(path)).toString("base64") };
    }
  }
  await visit(directory);
  return result;
}
export async function build() {
  const manifest = resolve(root, ".openai/hosting.json");
  const source = await readFile(resolve(root, "worker/index.js"), "utf8");
  const bundled = "const EMBEDDED_ASSETS=" + JSON.stringify(await assets()) + ";\n" + source.replace("export default createHandler();", "export default createHandler({ assets: EMBEDDED_ASSETS });");
  await mkdir(resolve(root, "dist/server"), { recursive: true });
  await writeFile(resolve(root, "dist/server/index.js"), bundled);
  try {
    const config = JSON.parse(await readFile(manifest, "utf8"));
    await mkdir(resolve(root, "dist/.openai"), { recursive: true });
    await writeFile(resolve(root, "dist/.openai/hosting.json"), JSON.stringify(config, null, 2) + "\n");
  } catch (error) { if (error.code !== "ENOENT") throw error; }
  console.log(JSON.stringify({ worker_built: true, bytes: Buffer.byteLength(bundled) }));
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await build();
