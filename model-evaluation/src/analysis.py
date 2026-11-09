"""Score saved classifier outputs and compare models on exactly matched examples."""
from __future__ import annotations
from collections import Counter
import csv
import io


def normalize(value):
    # Preserve native intent spelling, including capitals and question marks.
    return value.strip().strip('"\'`').strip().removesuffix('.').strip()


def csv_records(text):
    reader=csv.DictReader(io.StringIO(text,newline=''),strict=True)
    fields=reader.fieldnames
    if not fields or len(fields)!=len(set(fields)) or 'id' not in fields:
        raise ValueError('CSV requires unique columns including id.')
    rows=list(reader)
    if not rows or len(rows)>100000 or any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ValueError('CSV is empty, malformed or exceeds 100000 rows.')
    if any(not r['id'].strip() for r in rows) or len({r['id'] for r in rows})!=len(rows):
        raise ValueError('Each prediction needs a unique nonempty ID.')
    return rows


def prediction(row):
    for name in ('predicted','prediction','label'):
        if name in row:return normalize(row[name])
    raise ValueError('Predictions need predicted, prediction or label columns.')


def scored_rows(rows,labels):
    result=[]
    for row in rows:
        if not row.get('prompt','').strip() or row.get('expected') not in labels:
            raise ValueError('Reference rows need prompt and an exact expected intent label.')
        predicted=prediction(row)
        valid=predicted in labels and row.get('valid','True') not in (False,'False','false','0') and row.get('valid_label','True') not in (False,'False','false','0') and row.get('truncated','False') not in (True,'True','true','1')
        result.append({**row,'predicted':predicted,'valid':valid,'correct':valid and predicted==row['expected']})
    return result


def metrics(rows,labels):
    if not rows:raise ValueError('No rows to score.')
    per_intent={}
    for label in labels:
        tp=sum(r['expected']==label and r['correct'] for r in rows)
        fp=sum(r['expected']!=label and r['valid'] and r['predicted']==label for r in rows)
        fn=sum(r['expected']==label and not r['correct'] for r in rows)
        p=tp/(tp+fp) if tp+fp else 0.0;r=tp/(tp+fn) if tp+fn else 0.0
        per_intent[label]={'support':tp+fn,'precision':p,'recall':r,'f1':2*p*r/(p+r) if p+r else 0.0}
    incorrect=Counter((r['expected'],r['predicted'] if r['valid'] else '[invalid]') for r in rows if not r['correct'])
    correct=sum(r['correct'] for r in rows)
    return {'total':len(rows),'correct':correct,'accuracy':correct/len(rows),
            'invalid_predictions':sum(not r['valid'] for r in rows),
            'macro_f1':sum(r['f1'] for r in per_intent.values())/len(labels),'per_intent':per_intent,
            'confusions':[{'expected':a,'predicted':b,'count':n} for (a,b),n in incorrect.most_common()]}


def compare(reference,candidate,labels,allow_subset=False):
    reference_by_id={r['id']:r for r in reference};candidate_by_id={r['id']:r for r in candidate}
    if len(reference_by_id)!=len(reference) or len(candidate_by_id)!=len(candidate):raise ValueError('Duplicate model-output IDs.')
    if set(candidate_by_id)-set(reference_by_id):raise ValueError('Candidate contains unknown reference IDs.')
    if set(candidate_by_id)!=set(reference_by_id) and not allow_subset:raise ValueError('Model ID sets differ. Use --allow-subset only for a declared candidate subset.')
    left=[];right=[];pairs=[]
    for row in reference:
        if row['id'] not in candidate_by_id:continue
        other=candidate_by_id[row['id']]
        if any(k in other and other[k]!=row[k] for k in ('prompt','expected')):raise ValueError('Candidate text or gold label differs for '+row['id'])
        other=scored_rows([{**other,'prompt':row['prompt'],'expected':row['expected']}],labels)[0]
        status='both_correct' if row['correct'] and other['correct'] else 'reference_only' if row['correct'] else 'candidate_only' if other['correct'] else 'both_wrong'
        left.append(row);right.append(other);pairs.append({'id':row['id'],'prompt':row['prompt'],'expected':row['expected'],'reference_predicted':row['predicted'],'candidate_predicted':other['predicted'],'reference_correct':row['correct'],'candidate_correct':other['correct'],'outcome':status})
    if not pairs:raise ValueError('The model outputs share no examples.')
    outcomes=Counter(r['outcome'] for r in pairs)
    return left,right,pairs,{'rows':len(pairs),'reference_rows_available':len(reference),'omitted_reference_rows':len(reference)-len(pairs),
        'outcomes':dict(outcomes),'accuracy_difference':sum(r['correct'] for r in right)/len(right)-sum(r['correct'] for r in left)/len(left)}
