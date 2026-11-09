#!/usr/bin/env python3
"""Download, verify and prepare the real BANKING77 training/evaluation subsets."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from data_prep import prepare
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--cache-dir',type=Path,default=ROOT/'.state/dataset-cache')
p.add_argument('--output-dir',type=Path,default=ROOT/'data/prepared')
a=p.parse_args()
manifest=prepare(a.cache_dir,a.output_dir,json.loads((ROOT/'config/data.json').read_text()))
print(json.dumps(manifest['selection'],indent=2))
