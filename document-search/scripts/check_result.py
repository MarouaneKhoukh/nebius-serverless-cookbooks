#!/usr/bin/env python3
"""Verify a complete saved vector collection and its optional retrieval checks."""
from pathlib import Path
import argparse
import json
import math
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from embed import DIMENSIONS, MODEL, RecipeError, digest, load_chunks, load_index, read_json
from retrieval import aggregate, load_queries, source_metrics


def verify(input_dir,output):
    manifest,records=load_index(output)
    settings=read_json(output/'run.json')['settings']
    if manifest['model']!=MODEL or manifest['dimensions']!=DIMENSIONS:
        raise ValueError('The saved model/dimensions differ from this recipe.')
    chunks=load_chunks(input_dir,settings['chunk_words'])
    if digest({'schema':1,'chunks':chunks,'settings':settings})!=manifest['fingerprint']:
        raise ValueError('Saved vectors do not match the prepared input/settings.')
    by_id={r['id']:r for r in records}
    if len(by_id)!=len(chunks) or set(by_id)!={c['id'] for c in chunks}:
        raise ValueError('Saved chunk IDs do not match the complete input.')
    for chunk in chunks:
        if any(by_id[chunk['id']].get(k)!=v for k,v in chunk.items()):
            raise ValueError('A saved vector is joined to changed source text or metadata.')
    def lines(name):
        return [json.loads(l) for l in (output/name).read_text().splitlines() if l.strip()]
    vectors,metadata=lines('vectors.jsonl'),lines('metadata.jsonl')
    expected=[c['id'] for c in chunks]
    if [r['id'] for r in vectors]!=expected or [r['id'] for r in metadata]!=expected:
        raise ValueError('Exported vectors and metadata are missing, duplicated or reordered.')
    for vector,meta,chunk in zip(vectors,metadata,chunks):
        if vector['vector']!=by_id[chunk['id']]['vector']:
            # load_index normalizes for comparison, so allow harmless last-bit
            # rounding while still requiring the original exported unit vector.
            original=read_json(output/'items'/(chunk['id']+'.json'))['vector']
            if vector['vector']!=original:raise ValueError('Exported vector differs from its saved item.')
        norm=sum(x*x for x in vector['vector'])
        if len(vector['vector'])!=DIMENSIONS or not math.isfinite(norm) or abs(norm-1)>1e-5:
            raise ValueError('Exported vectors must be finite native-size unit vectors.')
        if any(meta.get(k)!=v for k,v in chunk.items()):
            raise ValueError('Exported metadata differs from its source chunk.')
    if manifest.get('corpus'):
        if (output/'DATA_LICENSE').read_bytes()!=(input_dir/'DATA_LICENSE').read_bytes():
            raise ValueError('Exported corpus license differs from the verified input.')
        if not (output/'DATA_SOURCE.md').is_file():raise ValueError('Dataset attribution is missing.')
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-dir',type=Path,default=Path('data/documents'))
    p.add_argument('--output-dir',type=Path,default=Path('results'))
    p.add_argument('--queries',type=Path,default=Path('data/queries.json'))
    p.add_argument('--require-checks',action='store_true')
    a=p.parse_args()
    try:
        manifest=verify(a.input_dir,a.output_dir)
        checked=0
        checks_path=a.output_dir/'retrieval-checks.json'
        if checks_path.exists():
            summary=read_json(checks_path)
            if summary['index_fingerprint']!=manifest['fingerprint']:raise ValueError('Query checks belong to a different index.')
            queries,_=load_queries(a.queries,{r['source'] for r in lines_for(a.output_dir/'metadata.jsonl')})
            results=summary['results']
            if [r['id'] for r in results]!=[q['id'] for q in queries]:raise ValueError('Query check IDs are incomplete or reordered.')
            for row,query in zip(results,queries):
                if any(row[k]!=query[k] for k in query):raise ValueError('Query text or expected sources changed.')
                for method in ('semantic','bm25'):
                    matches=row[method+'_matches']
                    if row[method]!=source_metrics(matches,query['expected_sources']):raise ValueError('Query metrics differ from the ranked sources.')
            for method in ('semantic','bm25'):
                if summary[method]!=aggregate(results,method,summary[method]['top_k']):raise ValueError('Aggregate query metrics differ from the result rows.')
            checked=len(queries)
        elif a.require_checks:raise ValueError('Run the retrieval check command before using --require-checks.')
        print(json.dumps({'documents':manifest['documents'],'chunks':manifest['chunks_saved'],'dimensions':manifest['dimensions'],'query_checks':checked,'fingerprint':manifest['fingerprint']},indent=2))
    except (OSError,ValueError,KeyError,RecipeError) as exc:
        print('Error:',str(exc),file=sys.stderr);raise SystemExit(1)


def lines_for(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


if __name__=='__main__':main()
