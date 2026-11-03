import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

test("frontend preserves connection, approval, privacy, and collection mutation contracts", () => {
  const fixturePath = fileURLToPath(new URL("./frontend.fixture.cjs", import.meta.url));
  const publicPath = fileURLToPath(new URL("../public/", import.meta.url));
  const result = spawnSync(process.execPath, [fixturePath, publicPath], {
    encoding: "utf8",
    timeout: 30_000,
  });
  assert.ifError(result.error);
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  assert.match(result.stdout, /^PASS:/);
});
