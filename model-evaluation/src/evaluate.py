#!/usr/bin/env python3
"""Evaluate saved real benchmark predictions locally; inference is a separate step."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile
from analysis import csv_records,scored_rows,metrics,compare
from analysis_report import render
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from check_result import validate


def read_csv(path):
    if path.stat().st_size>25*1024**2:raise ValueError('CSV exceeds the 25 MiB input limit.')
    return csv_records(path.read_text(encoding='utf-8-sig'))


def read_archive(path,labels):
    if path.resolve()==(ROOT/'data/reference-results.zip').resolve():
        pin=json.loads((ROOT/'data/reference.json').read_text())
        if path.stat().st_size!=pin['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=pin['sha256']:
            raise ValueError('Bundled reference result differs from its pinned source.')
    with zipfile.ZipFile(path) as archive:
        members=archive.infolist();names=[m.filename for m in members]
        if len(set(names))!=len(names) or any(Path(n).name!=n or n in {'.','..'} for n in names):raise ValueError('Archive needs unique flat filenames.')
        if sum(m.file_size for m in members)>500*1024**2:raise ValueError('Archive exceeds the 500 MiB limit.')
        if archive.testzip() is not None:raise ValueError('Corrupt result ZIP.')
        files={n:archive.read(n) for n in names}
    validate(files)
    contract=json.loads(files['run_contract.json'])
    if contract['labels']!=labels:raise ValueError('Archive taxonomy differs from --labels.')
    metadata={'model':contract['config']['model'],'model_revision':contract['config']['model_revision'],
              'dataset':contract['dataset'],'prompt_examples':len(contract.get('prompt_examples',[])),
              'artifact_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
              'inference_origin':'Saved Nebius Serverless AI prediction export; no model requests made by this evaluator.'}
    return csv_records(files['predictions.csv'].decode()),metadata,files


def write_csv(path,fields,rows):
    with path.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore',lineterminator='\n');writer.writeheader();writer.writerows(rows)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    source=p.add_mutually_exclusive_group()
    source.add_argument('--archive',type=Path,help='Complete result.zip from the bundled finite GPU Job')
    source.add_argument('--predictions',type=Path,help='CSV with id,prompt,expected,predicted (or prediction)')
    p.add_argument('--candidate',type=Path,help='Optional second model CSV with id,predicted; extra gold/text columns must match')
    p.add_argument('--allow-subset',action='store_true',help='Explicitly compare only candidate IDs when it covers a declared reference subset')
    p.add_argument('--labels',type=Path,default=ROOT/'data/categories.json')
    p.add_argument('--reference-name')
    p.add_argument('--candidate-name')
    p.add_argument('--output-dir',type=Path,default=Path('results'))
    p.add_argument('--no-report',action='store_true',help='Export raw CSV/JSON only for your own UI')
    p.add_argument('--template',type=Path,help='Optional replacement HTML template; default templates/report.html')
    a=p.parse_args(argv)
    try:
        labels=json.loads(a.labels.read_text())
        if not isinstance(labels,list) or not labels or len(set(labels))!=len(labels) or any(not isinstance(v,str) or not v or v!=v.strip() for v in labels):raise ValueError('Labels must be unique nonempty exact strings.')
        files={}
        if a.predictions:
            raw=read_csv(a.predictions);provenance={'input':'user_csv','sha256':hashlib.sha256(a.predictions.read_bytes()).hexdigest()}
        else:
            raw,provenance,files=read_archive(a.archive or ROOT/'data/reference-results.zip',labels)
        reference=scored_rows(raw,labels)
        reference_name=a.reference_name or provenance.get('model','Reference model')
        candidate=None;candidate_name=None
        if a.candidate:
            candidate=read_csv(a.candidate);candidate_name=a.candidate_name or 'Candidate model'
        elif not a.predictions and all(r.get('baseline_predicted') for r in raw):
            candidate=[{'id':r['id'],'predicted':r['baseline_predicted']} for r in raw]
            candidate_name=a.candidate_name or 'Word/bigram Naive Bayes (CPU)'
        pairs=[];comparison=None
        if candidate is not None:
            reference,candidate,pairs,comparison=compare(reference,candidate,labels,a.allow_subset)
            comparison['candidate']=metrics(candidate,labels)
        summary={'schema':1,'dataset':'BANKING77' if not a.predictions else 'User-supplied labeled examples',
                 'reference_name':reference_name,'candidate_name':candidate_name,'labels':labels,
                 'reference':metrics(reference,labels),'comparison':comparison,'provenance':provenance,
                 'notes':['Different supervision or prompts are not a controlled fine-tuning comparison.',
                          'The bundled benchmark has known normalized train/test text overlaps, documented in data/SOURCE.md.',
                          'Scoring consumes saved outputs and makes no paid inference requests.']}
        if a.output_dir.exists() and any(a.output_dir.iterdir()):raise ValueError('Output directory is not empty; choose a new one to preserve earlier results.')
        a.output_dir.mkdir(parents=True,exist_ok=True)
        (a.output_dir/'scores.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
        write_csv(a.output_dir/'predictions.csv',['id','prompt','expected','predicted','valid','correct'],reference)
        write_csv(a.output_dir/'mistakes.csv',['id','prompt','expected','predicted','valid','correct'],[r for r in reference if not r['correct']])
        write_csv(a.output_dir/'comparisons.csv',['id','prompt','expected','reference_predicted','candidate_predicted','reference_correct','candidate_correct','outcome'],pairs)
        if 'DATA_LICENSE' in files:
            (a.output_dir/'DATA_LICENSE').write_bytes(files['DATA_LICENSE'])
        if 'DATA_SOURCE.md' in files:
            # Preserve the pinned original archive; adapt its links to the new
            # analysis folder, which has different attribution filenames.
            attribution=files['DATA_SOURCE.md'].decode('utf-8')
            attribution=attribution.replace('](source.json)','](dataset_provenance.json)').replace('](LICENSE)','](DATA_LICENSE)')
            (a.output_dir/'DATA_SOURCE.md').write_text(attribution,encoding='utf-8')
        if 'dataset' in provenance:
            (a.output_dir/'dataset_provenance.json').write_text(json.dumps(provenance['dataset'],indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        if not a.no_report:(a.output_dir/'report.html').write_text(render(summary,reference,candidate,pairs,ROOT,a.template),encoding='utf-8')
        print(json.dumps({'rows':len(reference),'reference_accuracy':summary['reference']['accuracy'],
                          'candidate_accuracy':comparison['candidate']['accuracy'] if comparison else None,
                          'comparison_outcomes':comparison['outcomes'] if comparison else None,
                          'output':str(a.output_dir)},indent=2))
        return 0
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile) as exc:
        print('Error:',str(exc),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
