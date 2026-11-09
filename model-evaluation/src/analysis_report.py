"""Optional HTML presentation; scoring and CSV output do not depend on this UI."""
import html
from pathlib import Path


def table(headers,rows):
    escape=lambda value:html.escape(str(value),quote=True)
    return '<div class="table"><table><thead><tr>'+''.join('<th>'+escape(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+escape(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'


def render(summary,reference,candidate,pairs,root,template=None):
    escape=lambda value:html.escape(str(value),quote=True)
    template=Path(template) if template else root/'templates/report.html'
    markup=template.read_text(encoding='utf-8')
    baseline=summary.get('comparison')
    def card(name,stats):return '<section class="card">'+escape(name)+'<strong>'+f"{stats['accuracy']:.1%}"+'</strong><small>'+f"{stats['correct']} / {stats['total']} correct · macro F1 {stats['macro_f1']:.1%}"+'</small></section>'
    cards=card(summary['reference_name'],summary['reference'])
    if baseline:cards+=card(summary['candidate_name'],baseline['candidate'])
    if pairs:
        errors=[r for r in pairs if r['outcome']!='both_correct']
        rows=[[r[k] for k in ['prompt','expected','reference_predicted','candidate_predicted','outcome']] for r in errors[:100]]
        errors_table=table(['Request','Expected','Reference','Candidate','Outcome'],rows)
    else:
        errors=[r for r in reference if not r['correct']]
        errors_table=table(['Request','Expected','Prediction'],[[r['prompt'],r['expected'],r['predicted']] for r in errors[:100]])
    confusions=summary['reference']['confusions'][:20]
    confusions_table=table(['Expected','Predicted','Count'],[[r['expected'],r['predicted'],r['count']] for r in confusions])
    values={'logo':(root/'docs/brand/nebius-logo.svg').read_text() if '{{logo}}' in markup else '','cards':cards,
            'scope':escape(f"{summary['reference']['total']} matched labeled questions · {len(summary['labels'])} allowed intents. Invalid labels count as incorrect."),
            'comparison':escape('Comparison uses the same IDs, text and expected labels for both models.' if baseline else 'No candidate model was supplied.'),
            'errors':errors_table,'confusions':confusions_table,
            'review_note':escape(f'Showing up to 100 of {len(errors)} requests needing inspection; use the CSVs for every result.')}
    for key,value in values.items():markup=markup.replace('{{'+key+'}}',value)
    return markup
