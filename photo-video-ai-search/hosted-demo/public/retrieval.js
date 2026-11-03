/* Hybrid visual/name retrieval. Scores are ranking signals, never confidence %. */
(() => {
  "use strict";
  const wrappers = new Set([
    "a", "an", "the", "of", "for", "some", "my", "me", "please", "show",
    "find", "search", "looking", "look", "image", "images", "photo", "photos",
    "picture", "pictures", "photograph", "photographs",
  ]);
  const NAME_BOOST = 0.15;

  function singular(word) {
    if (word.length > 4 && word.endsWith("ies")) return word.slice(0, -3) + "y";
    if (word.length > 3 && word.endsWith("s") && !/(ss|us|is)$/.test(word)) return word.slice(0, -1);
    return word;
  }

  function terms(value) {
    if (typeof value !== "string") return new Set();
    const words = value.normalize("NFKC").toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
    return new Set(words.filter(word => !wrappers.has(word)).map(singular));
  }

  function nameTerms(item) {
    let source = typeof item.source_name === "string" ? item.source_name : "";
    try { source = decodeURIComponent(source); } catch { /* Keep malformed names as plain text. */ }
    let basename = source.replaceAll("\\", "/").split("/").pop() || "";
    const dot = basename.lastIndexOf(".");
    if (dot > 0) basename = basename.slice(0, dot);
    return new Set([...terms(item.title), ...terms(basename)]);
  }

  function rankResults(query, items, options = {}) {
    const threshold = options.semanticThreshold ?? 0.25;
    if (!Number.isFinite(threshold) || threshold < -1 || threshold > 1) {
      throw new TypeError("Semantic threshold must be a finite cosine between -1 and 1.");
    }
    const limit = options.limit;
    if (limit !== undefined && (!Number.isInteger(limit) || limit < 1)) {
      throw new TypeError("Result limit must be a positive integer.");
    }
    const queryTerms = terms(query);
    let ranked = Array.from(items, original => {
      const score = typeof original.score === "number" && Number.isFinite(original.score) ? original.score : null;
      const names = nameTerms(original);
      const matched = [...queryTerms].filter(word => names.has(word)).sort();
      const coverage = queryTerms.size ? matched.length / queryTerms.size : 0;
      const named = queryTerms.size > 0 && matched.length === queryTerms.size;
      const matchType = named ? "named" : score !== null && score >= threshold ? "semantic" : "related";
      return {
        ...original,
        match_type: matchType,
        matched_terms: matched,
        metadata_coverage: coverage,
        semantic_score: score,
        ranking_score: (score ?? -1) + NAME_BOOST * coverage,
      };
    });
    // Qualifying matches get limited slots before rejected diagnostic candidates.
    // Stable ties retain the visual retrieval order; raw scores are unchanged.
    ranked.sort((a, b) => Number(b.match_type !== "related") - Number(a.match_type !== "related")
      || b.ranking_score - a.ranking_score);
    if (limit !== undefined) ranked = ranked.slice(0, limit);
    const matches = ranked.filter(item => item.match_type !== "related");
    const scores = ranked.map(item => item.semantic_score).filter(score => score !== null);
    return {
      items: ranked,
      match_found: matches.length > 0,
      match_basis: matches.some(item => item.match_type === "named") ? "named"
        : matches.length ? "semantic" : ranked.length ? "related" : "empty",
      matched_count: matches.length,
      best_score: scores.length ? Math.max(...scores) : null,
    };
  }

  const api = Object.freeze({ rankResults });
  if (typeof window !== "undefined") window.NebiusRetrieval = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
