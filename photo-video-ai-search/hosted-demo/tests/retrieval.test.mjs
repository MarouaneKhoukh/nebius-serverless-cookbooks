import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const context = { window: {} };
vm.createContext(context);
vm.runInContext(readFileSync(new URL("../public/retrieval.js", import.meta.url), "utf8"), context);
const { rankResults } = context.window.NebiusRetrieval;

test("visual match threshold accepts its boundary and rejects a lower score", () => {
  const result = rankResults("espresso", [
    { title: "Coffee beans", source_name: "coffee.jpg", score: .249 },
    { title: "A cup", source_name: "cup.jpg", score: .25 },
  ]);
  assert.equal(result.matched_count, 1);
  assert.equal(result.items[0].title, "A cup");
  assert.equal(result.items[0].match_type, "semantic");
  assert.equal(result.items[1].match_type, "related");
  assert.equal(result.items[1].semantic_score, .249, "raw cosine remains unchanged");
});

test("low nearest neighbors do not constitute a match", () => {
  const result = rankResults("football", [
    { title: "City at night", source_name: "city-at-night.jpg", score: .1356 },
    { title: "Coffee beans", source_name: "coffee-beans.jpg", score: .10 },
  ]);
  assert.equal(result.match_found, false);
  assert.equal(result.matched_count, 0);
  assert.equal(result.items.length, 2, "rejected candidates remain available for diagnostics");
  assert(result.items.every(item => item.match_type === "related"));
});

test("visual synonyms and complete name matches provide independent evidence", () => {
  const photo = { title: "Coffee beans", source_name: "coffee-beans.jpg", score: .2812 };
  assert.equal(rankResults("espresso", [photo]).items[0].match_type, "semantic");
  assert.equal(rankResults("coffee", [{ ...photo, score: .20 }]).items[0].match_type, "named");
  assert.equal(rankResults("coffee on a football pitch", [{ ...photo, score: .10 }]).match_found, false,
    "a partial filename overlap cannot turn an unrelated description into a match");
});

test("limited results reserve space for matches before partially named rejected candidates", () => {
  const candidates = [
    { title: "Warm", source_name: "warm.jpg", score: .24 },
    { title: "Untitled", source_name: "image-01.jpg", score: .26 },
    { title: "Untitled two", source_name: "image-02.jpg", score: .28 },
  ];
  const limited = rankResults("warm drink", candidates.slice(0, 2), { limit: 1 });
  assert.equal(limited.items.length, 1);
  assert.equal(limited.items[0].title, "Untitled");
  assert.equal(limited.match_found, true);
  assert.equal(limited.matched_count, 1);
  const full = rankResults("warm drink", candidates, { limit: 3 });
  assert.equal(full.items.length, 3);
  assert.deepEqual(Array.from(full.items, item => item.title), ["Untitled two", "Untitled", "Warm"]);
  assert.equal(full.items[2].match_type, "related");
  assert(full.items[2].ranking_score > full.items[0].ranking_score,
    "partial-name boost cannot consume a qualifying match's limited slot");
});
