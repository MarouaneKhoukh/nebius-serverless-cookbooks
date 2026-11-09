#!/usr/bin/env python3
"""Check a completed batch export and optionally unpack it for the browser report."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from artifacts import digest_json

REQUIRED = {'summary.json', 'predictions.csv', 'review.csv', 'mistakes.csv', 'input.csv',
            'report.html', 'run_contract.json', 'attempts.json', 'config.json',
            'dataset_provenance.json', 'runtime.json', 'DATA_LICENSE', 'DATA_SOURCE.md'}


def validate(files, *, require_resume=False, allow_partial=False):
    missing = REQUIRED - set(files)
    if missing:
        raise ValueError('Missing result files: ' + ', '.join(sorted(missing)))
    def document(name):
        return json.loads(files[name].decode('utf-8'))
    def rows(name):
        return list(csv.DictReader(io.StringIO(files[name].decode('utf-8'), newline='')))
    summary, contract, attempts = document('summary.json'), document('run_contract.json'), document('attempts.json')
    if document('dataset_provenance.json') != contract['dataset']:
        raise ValueError('Dataset provenance differs from the run contract.')
    license_hash = contract['dataset'].get('source_files', {}).get('LICENSE', {}).get('sha256')
    if not license_hash or hashlib.sha256(files['DATA_LICENSE']).hexdigest() != license_hash:
        raise ValueError('Dataset license differs from the verified source license.')
    if not files['DATA_SOURCE.md'].strip():
        raise ValueError('Dataset attribution is empty.')
    original, predictions = rows('input.csv'), rows('predictions.csv')
    original_ids, predicted_ids = [r['id'] for r in original], [r['id'] for r in predictions]
    if not original or len(set(original_ids)) != len(original_ids):
        raise ValueError('Input must contain distinct requests.')
    if len(set(predicted_ids)) != len(predicted_ids) or set(predicted_ids) - set(original_ids):
        raise ValueError('Predictions contain duplicate or unknown IDs.')
    if digest_json(original) != contract['input_sha256'] or digest_json(contract) != summary['contract_hash']:
        raise ValueError('Input or run contract checksum does not match.')
    if document('config.json') != contract['config'] or summary['model'] != contract['config']['model']:
        raise ValueError('Model configuration differs from the recorded run.')
    if original_ids != [r for batch in contract['partitions'] for r in batch]:
        raise ValueError('Input IDs do not match the batch partitioning.')
    if summary['total'] != len(original) or summary['completed'] != len(predictions):
        raise ValueError('Summary counts do not match the files.')
    if summary['remaining'] != len(original) - len(predictions):
        raise ValueError('Remaining request count is inconsistent.')
    complete = len(predictions) == len(original)
    if bool(summary['complete']) != complete or not complete and not allow_partial:
        raise ValueError('The batch is incomplete; resume it, or use --allow-partial to inspect the saved portion.')
    predicted_set = set(predicted_ids)
    wanted = [r for r in original_ids if r in predicted_set]
    if predicted_ids != wanted:
        raise ValueError('Predictions are not in the prepared input order.')
    by_id = {r['id']:r for r in original}
    for row in predictions:
        if any(row.get(k) != by_id[row['id']][k] for k in ['prompt','expected']):
            raise ValueError('A prediction was joined to different input text or expected label.')
    mistakes, review = rows('mistakes.csv'), rows('review.csv')
    if len(mistakes) != summary['mistakes'] or len(review) != summary['review_rows']:
        raise ValueError('Review/mistake files differ from the summary.')
    if 'Powered by Nebius Serverless AI' not in files['report.html'].decode('utf-8'):
        raise ValueError('The report is missing its branding.')
    if attempts != summary['attempts'] or not attempts:
        raise ValueError('Attempt evidence is missing or inconsistent.')
    if require_resume and not any(a.get('reused_rows',0)>0 for a in attempts):
        raise ValueError('No attempt reports reused completed rows.')
    return {'completed':len(predictions),'total':len(original),'accuracy':summary['accuracy'],
            'baseline_accuracy':summary['baseline'].get('accuracy'),
            'reused_rows':max(a.get('reused_rows',0) for a in attempts),
            'contract_hash':summary['contract_hash']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path,help='Downloaded result.zip or an unpacked result directory')
    p.add_argument('--output',type=Path,help='Unpack a verified ZIP into a new or empty directory')
    p.add_argument('--require-resume',action='store_true')
    p.add_argument('--allow-partial',action='store_true')
    a=p.parse_args()
    try:
        if a.source.is_dir():
            if a.output:
                raise ValueError('--output is for ZIP files; this result is already unpacked.')
            files={q.name:q.read_bytes() for q in a.source.iterdir() if q.is_file()}
        else:
            with zipfile.ZipFile(a.source) as z:
                members=z.infolist();names=[m.filename for m in members]
                if len(set(names))!=len(names) or any(Path(n).name!=n or n in {'.','..'} for n in names):
                    raise ValueError('Result ZIP must have unique, flat filenames.')
                if sum(m.file_size for m in members)>500*1024**2:
                    raise ValueError('Result ZIP exceeds the 500 MiB inspection limit.')
                if z.testzip() is not None:
                    raise ValueError('The ZIP is incomplete or corrupt.')
                files={name:z.read(name) for name in names}
        result=validate(files,require_resume=a.require_resume,allow_partial=a.allow_partial)
        if a.output:
            if a.output.exists() and any(a.output.iterdir()):
                raise ValueError('Output directory is not empty; choose a new one to preserve previous results.')
            a.output.mkdir(parents=True,exist_ok=True)
            for name,data in files.items():(a.output/name).write_bytes(data)
        print(json.dumps(result,indent=2))
        print('Verified completed requests, their input joins, and saved run evidence.')
    except (OSError,ValueError,KeyError,zipfile.BadZipFile) as exc:
        print('Error:',str(exc),file=sys.stderr);raise SystemExit(1)


if __name__=='__main__':main()
