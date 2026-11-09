#!/usr/bin/env python3
"""Try source retrieval locally with BM25 before renting a GPU."""
from pathlib import Path
import argparse
import json
import sys
import time
import shutil
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from embed import RecipeError, load_chunks, report, write_json
from retrieval import BM25, aggregate, load_queries, source_metrics


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-dir', type=Path, default=Path('data/documents'))
    p.add_argument('--queries', type=Path, default=Path('data/queries.json'))
    p.add_argument('--output-dir', type=Path, default=Path('results-bm25'))
    p.add_argument('--chunk-words', type=int, default=160)
    p.add_argument('--top-k', type=int, choices=range(1,21), default=5)
    a = p.parse_args()
    started = time.perf_counter()
    try:
        chunks = load_chunks(a.input_dir, a.chunk_words)
        queries, provenance = load_queries(a.queries, {c['source'] for c in chunks})
        baseline = BM25(chunks)
        rows = []
        for query in queries:
            matches = baseline.search(query['text'], top_k=a.top_k)
            rows.append({**query, 'bm25': source_metrics(matches, query['expected_sources']), 'matches': matches})
        result = {'schema':1,'model':'BM25, CPU only','documents':len({c['source'] for c in chunks}),
                  'chunks':len(chunks),'query_provenance':provenance,
                  'metrics':aggregate(rows,'bm25',a.top_k),'results':rows,
                  'local_seconds':time.perf_counter()-started}
        write_json(a.output_dir / 'retrieval-checks.json',result)
        if (a.input_dir / 'DATA_LICENSE').is_file():
            shutil.copyfile(a.input_dir / 'DATA_LICENSE', a.output_dir / 'DATA_LICENSE')
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'data/SOURCE.md', a.output_dir / 'DATA_SOURCE.md')
        report(a.output_dir / 'report.html','Search Python Documentation with BM25',
               f"{len(queries)} FAQ questions · {len(chunks)} chunks · source hit@{a.top_k}: {result['metrics']['hit_at_k']:.1%}",
               ['question','expected','first result','source in top k'],
               [{'question':r['text'],'expected':', '.join(r['expected_sources']),
                 'first result':r['matches'][0]['source'],'source in top k':r['bm25']['hit_at_k']} for r in rows])
        print(json.dumps({k:v for k,v in result.items() if k!='results'},indent=2))
        print('Wrote',a.output_dir / 'retrieval-checks.json','and',a.output_dir / 'report.html')
    except (OSError,ValueError,RecipeError) as exc:
        print('Error:',str(exc),file=sys.stderr)
        raise SystemExit(1)


if __name__=='__main__':
    main()
