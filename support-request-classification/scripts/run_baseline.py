#!/usr/bin/env python3
"""Try the trained CPU baseline before renting a GPU; no cloud account required."""
import argparse
import csv
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from baseline import predict
from dataset import load_dataset

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--limit',type=int,default=0)
p.add_argument('--output-dir',type=Path,default=Path('results-cpu'))
a=p.parse_args()
try:
    rows,labels,source,training=load_dataset(Path('.state/data'),limit=a.limit,seed=42)
    start=time.monotonic();predictions=predict(training,rows,labels);seconds=time.monotonic()-start
    correct=sum(predictions[r['id']]==r['expected'] for r in rows)
    score={'model':'word/bigram multinomial Naive Bayes','train_rows':len(training),
           'test_rows':len(rows),'correct':correct,'accuracy':correct/len(rows),
           'fit_and_predict_seconds':seconds,'dataset':source,
           'note':'Local CPU measurement. Timing excludes download; this is not a GPU or cloud-cost measurement.'}
    a.output_dir.mkdir(parents=True,exist_ok=True)
    with (a.output_dir/'predictions.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['id','prompt','expected','predicted']);w.writeheader()
        for r in rows:w.writerow({**r,'predicted':predictions[r['id']]})
    (a.output_dir/'summary.json').write_text(json.dumps(score,indent=2)+'\n')
    root=Path(__file__).resolve().parents[1]
    for name,target in [('LICENSE','DATA_LICENSE'),('SOURCE.md','DATA_SOURCE.md')]:
        (a.output_dir/target).write_bytes((root/'data'/name).read_bytes())
    print(f'{correct}/{len(rows)} correct ({100*correct/len(rows):.1f}%) in {seconds:.2f}s for CPU fitting and prediction.')
    print(f'Saved predictions and score in {a.output_dir}. No GPU or cloud resource was created.')
except (OSError,ValueError) as exc:
    p.exit(1,f'Error: {exc}\n')
