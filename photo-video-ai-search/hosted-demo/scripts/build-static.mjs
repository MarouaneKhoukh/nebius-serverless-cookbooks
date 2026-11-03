/** Only public assets are published; the API is bundled separately by Vercel. */
import { cp, mkdir, rm } from "node:fs/promises";
import { resolve } from "node:path";
import { root } from "./build.mjs";

const output = resolve(root, "dist");
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
await cp(resolve(root, "public"), output, { recursive: true });
console.log("Static gallery built in dist/.");
