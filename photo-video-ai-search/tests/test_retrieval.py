"""Ranking-policy checks; live model relevance is validated separately."""

import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from media_search.retrieval import NAME_BOOST, rank_results, terms
from media_search.config import Settings


def result(title, score, source_name="unnamed.jpg", **extra):
    return dict(id=title, title=title, source_name=source_name, score=score, **extra)


def test_real_coffee_regression_is_named_match_below_old_threshold():
    # Captured live Qwen scores, not synthetic evidence of model accuracy.
    candidates = [result("coffee beans", .346449), result("coffee", .304198),
                  result("city at night", .060779), result("mountain lake", .057065)]
    before = copy.deepcopy(candidates)
    ranked = rank_results("coffee", candidates)
    assert ranked["match_found"] is True
    assert ranked["match_basis"] == "named"
    assert ranked["matched_count"] == 2
    assert ranked["items"][0]["title"] == "coffee beans"
    assert ranked["items"][0]["match_type"] == "named"
    assert ranked["items"][0]["score"] == .346449
    assert ranked["items"][0]["semantic_score"] == .346449
    assert ranked["items"][0]["ranking_score"] == pytest.approx(.346449 + NAME_BOOST)
    assert candidates == before


@pytest.mark.parametrize("query", ["COFFEE", "show me photos of coffee", "coffee!", "coffee beans", "beans"])
def test_natural_name_queries_and_case_punctuation(query):
    ranked = rank_results(query, [result("Coffee beans", .30, "coffee-beans.jpg")])
    assert ranked["match_found"]
    assert ranked["items"][0]["match_type"] == "named"


def test_filename_match_is_word_based_and_does_not_match_paths_or_extensions():
    candidates = [result("untitled", .25, "coffee%20beans.JPG"),
                  result("untitled", .24, "/coffee/steam.jpg"),
                  result("untitled", .23, "coffeetable.jpg"),
                  result("untitled", .22, "portrait.coffee")]
    ranked = rank_results("coffee", candidates)
    assert [x["match_type"] for x in ranked["items"]] == ["named", "related", "related", "related"]
    assert rank_results("tea", candidates, semantic_threshold=.35)["match_found"] is False


@pytest.mark.parametrize("query", ["coffee cup", "coffee without milk", "not coffee", "coffee blue"])
def test_partial_or_negated_description_is_not_claimed_as_name_match(query):
    # Isolate the name rule; semantic evidence is tested independently below.
    ranked = rank_results(query, [result("coffee beans", .30)], semantic_threshold=.35)
    assert ranked["match_found"] is False
    assert ranked["items"][0]["match_type"] == "related"
    assert ranked["items"][0]["metadata_coverage"] < 1


def test_name_boost_changes_ranking_but_cannot_override_large_visual_difference():
    weakly_renamed = result("coffee beans", -.10)
    visually_relevant = result("untitled", .50)
    close_visual = result("untitled two", .40)
    assert rank_results("coffee", [weakly_renamed, visually_relevant])["items"][0]["title"] == "untitled"
    assert rank_results("coffee", [close_visual, result("coffee beans", .34)])["items"][0]["title"] == "coffee beans"


def test_semantic_match_does_not_require_matching_name_and_related_results_are_kept():
    ranked = rank_results("warm drink", [result("untitled", .48), result("city at night", .08)])
    assert ranked["match_found"] is True
    assert ranked["match_basis"] == "semantic"
    assert ranked["items"][0]["match_type"] == "semantic"
    assert ranked["items"][1]["match_type"] == "related"
    assert len(ranked["items"]) == 2


def test_empty_and_wrapper_only_queries_never_produce_fake_name_matches():
    assert rank_results("coffee", [])["match_basis"] == "empty"
    ranked = rank_results("show me photos", [result("any title", .1)])
    assert ranked["match_found"] is False
    assert ranked["match_basis"] == "related"


def test_unicode_and_common_plural_names():
    assert terms("BEANS, cities ＣＯＦＦＥＥ") == {"bean", "city", "coffee"}
    assert rank_results("city", [result("city at night", .30)])["match_found"]
    assert rank_results("café", [result("café beans", .30)])["match_found"]


def test_limit_and_invalid_scores_do_not_turn_into_confidence():
    ranked = rank_results("coffee", [result("untitled", .4), result("coffee", float("nan")),
                                     result("coffee beans", None)], limit=1)
    assert ranked["items"][0]["title"] == "untitled"
    assert ranked["matched_count"] == 1
    assert ranked["best_score"] == .4
    with pytest.raises(ValueError):
        rank_results("coffee", [], semantic_threshold=float("nan"))


def test_limit_prioritizes_matches_before_partially_named_rejected_candidates():
    candidates = [result("warm", .24, "warm.jpg"),
                  result("untitled", .26, "image-01.jpg"),
                  result("untitled two", .28, "image-02.jpg")]
    limited = rank_results("warm drink", candidates[:2], limit=1)
    assert len(limited["items"]) == 1
    assert limited["items"][0]["title"] == "untitled"
    assert limited["match_found"] is True
    assert limited["matched_count"] == 1
    full = rank_results("warm drink", candidates, limit=3)
    assert len(full["items"]) == 3
    assert [item["title"] for item in full["items"]] == ["untitled two", "untitled", "warm"]
    assert full["items"][2]["match_type"] == "related"
    assert full["items"][2]["ranking_score"] > full["items"][0]["ranking_score"]


def test_browser_and_python_ranking_policies_agree():
    """The hosted and local demos must agree on real regressions and edge cases."""
    if not shutil.which("node"):
        pytest.skip("Node.js is not installed; browser module parity check is optional locally.")
    path = Path(__file__).resolve().parents[1] / "hosted-demo/public/retrieval.js"
    cases = [
        {"query": query, "items": [result("coffee beans", .346449, "coffee-beans.jpg"),
                                  result("city at night", .32, "city-at-night.jpg"),
                                  result("untitled", .41, "untitled.jpg")]}
        for query in ("coffee", "coffee beans", "bean", "city", "photos of cities", "not coffee", "tea", "show me photos")
    ]
    cases.append({"query": "café", "items": [result("Café beans", .3)]})
    cases.extend({"query": "warm drink", "items": [result("warm", .24), result("untitled", .26)],
                  "limit": limit} for limit in (1, 2))
    script = ("const fs=require('node:fs'),vm=require('node:vm'); const browser={window:{}};"
              "vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),browser);"
              "const {rankResults}=browser.window.NebiusRetrieval;"
              "const cases=JSON.parse(fs.readFileSync(0,'utf8'));"
              "process.stdout.write(JSON.stringify(cases.map(c=>rankResults(c.query,c.items,{limit:c.limit}))));")
    completed = subprocess.run(["node", "-e", script, str(path)], input=json.dumps(cases),
                               capture_output=True, text=True, check=True, timeout=10)
    browser = json.loads(completed.stdout)
    assert browser == [rank_results(case["query"], case["items"], limit=case.get("limit")) for case in cases]


def test_captured_visual_scores_accept_sample_positives_and_abstain_for_absent_queries():
    """Regression for the tiny sample used to fit the cutoff, not a benchmark.

    All descriptive titles and filenames are masked before ranking. Replaying
    captured scores verifies the display policy without making inference calls;
    it does not independently establish general retrieval accuracy.
    """
    path = Path(__file__).parent / "fixtures/search-relevance-scores.json"
    fixture = json.loads(path.read_text())
    positives = absent = 0
    assert Settings().match_threshold == fixture["fitted_semantic_threshold"] == .25
    for query in fixture["queries"]:
        candidates = [dict(id=item["image_id"], title="Untitled", source_name=f'{item["image_id"]}.jpg',
                           score=item["cosine"]) for item in query["scores"]]
        ranked = rank_results(query["query"], candidates)
        accepted = [item for item in ranked["items"] if item["match_type"] != "related"]
        assert len(ranked["items"]) == 4, "Rejected scores remain available for diagnostics."
        assert all(not item["matched_terms"] for item in ranked["items"])
        expected = query["expected_image_id"]
        if expected is None:
            absent += 1
            assert ranked["match_found"] is False, query["query"]
            assert accepted == [], query["query"]
        else:
            positives += 1
            assert ranked["match_found"] is True, query["query"]
            assert ranked["match_basis"] == "semantic", query["query"]
            assert [item["id"] for item in accepted] == [expected], query["query"]
            assert ranked["items"][0]["id"] == expected, query["query"]
    assert (positives, absent) == (7, 5)


def test_default_threshold_is_consistent_with_environment_configuration(monkeypatch):
    from media_search import config
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.delenv("MATCH_THRESHOLD", raising=False)
    assert config.Settings.from_env().match_threshold == Settings().match_threshold == .25
    monkeypatch.setenv("MATCH_THRESHOLD", "0.42")
    assert config.Settings.from_env().match_threshold == .42


def test_persistent_frontend_shows_no_unrelated_cards_and_keeps_browsing_available():
    """Exercise the actual UI event flow using captured, non-inference responses."""
    if not shutil.which("node"):
        pytest.skip("Node.js is not installed; browser event-flow check is optional locally.")
    fixture = json.loads((Path(__file__).parent / "fixtures/search-relevance-scores.json").read_text())
    responses = {}
    for query in fixture["queries"]:
        if query["query"] not in {"football", "espresso"}:
            continue
        candidates = [dict(id=item["image_id"], title="Untitled", source_name=f'{item["image_id"]}.jpg',
                           media_url=f'/media/{item["image_id"]}.jpg', score=item["cosine"])
                      for item in query["scores"]]
        responses[query["query"]] = {**rank_results(query["query"], candidates), "generation_available": True}
    path = Path(__file__).resolve().parents[1] / "media_search/static/app.js"
    script = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const results = JSON.parse(fs.readFileSync(0, 'utf8'));
class Element {
  constructor(tag = 'div') { this.tag = tag; this.children = []; this.listeners = {}; this.hidden = false; this.value = ''; this.textContent = ''; this.classList = {toggle(){}}; this.dataset = {}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  after(element) { this.afterElement = element; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute() {} focus() {} removeAttribute() {}
}
const nodes = new Map(), calls = [], library = results.football.items;
const node = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
const context = { console, URL, URLSearchParams, setTimeout, clearTimeout,
  window: {location: {origin: 'http://localhost:8080'}},
  document: {getElementById: node, createElement: tag => new Element(tag)},
  fetch: async (path, options = {}) => {
    calls.push(path);
    let data;
    if (path === '/api/status') data = {generation_enabled: true};
    else if (path.startsWith('/api/gallery?')) data = {items: library, next_offset: null};
    else if (path === '/api/session') data = {csrf_token: 'fixture'};
    else if (path === '/api/search') data = results[JSON.parse(options.body).query];
    else throw new Error('Unexpected request: ' + path);
    return {ok: true, json: async () => data};
  }
};
const flush = async () => {for (let i = 0; i < 10; i++) await new Promise(setImmediate);};
const event = (id, name = 'click') => node(id).listeners[name]({preventDefault(){}});
const imageCount = element => (element.tag === 'img' ? 1 : 0) + element.children.reduce((total, child) => total + imageCount(child), 0);
(async () => {
  vm.createContext(context); vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
  await flush(); assert.equal(node('gallery').children.length, 4, 'browsing shows the collection');
  node('query').value = 'football'; await event('search-form', 'submit'); await flush();
  assert.equal(node('gallery').children.length, 0, 'absent query never promotes nearest neighbors');
  assert.equal(node('results-title').textContent, 'No matching photos for “football”');
  assert.equal(node('empty-state').hidden, false);
  assert.equal(node('result-count').textContent, '0 results');
  assert.equal(node('create-offer').hidden, false, 'generation stays opt-in');
  assert.equal(imageCount(node('gallery').afterElement), 0, 'diagnostics contain no result cards');
  await event('clear-button'); await flush(); assert.equal(node('gallery').children.length, 4, 'back to collection restores browsing');
  node('query').value = 'espresso'; await event('search-form', 'submit'); await flush();
  assert.equal(node('gallery').children.length, 1, 'visual synonym displays its accepted image only');
  assert.equal(node('empty-state').hidden, true);
  assert.equal(node('results-title').textContent, 'Matches for “espresso”');
  assert(!calls.some(path => path.startsWith('/api/generations')), 'search never generates');
  console.log('PASS');
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    completed = subprocess.run(["node", "-e", script, str(path)], input=json.dumps(responses),
                               capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "PASS"
