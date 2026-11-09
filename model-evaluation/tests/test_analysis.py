"""Offline tests of actual reference scoring, model alignment and archive integrity."""
import csv
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from analysis import csv_records,scored_rows,metrics,compare,normalize
import evaluate
from analysis_report import render

class AnalysisTests(unittest.TestCase):
    def setUp(self):self.labels=['Refund_not_showing_up','reverted_card_payment?']
    def rows(self):
        return [{'id':'a','prompt':'original one','expected':self.labels[0],'predicted':self.labels[0]},
                {'id':'b','prompt':'original two','expected':self.labels[1],'predicted':self.labels[0]}]
    def test_exact_native_label_and_invalid_flags(self):
        self.assertEqual(normalize('"Refund_not_showing_up"'),'Refund_not_showing_up')
        rows=self.rows();rows[0]['truncated']='True'
        scored=scored_rows(rows,self.labels)
        self.assertEqual(metrics(scored,self.labels)['correct'],0)
        self.assertEqual(metrics(scored,self.labels)['invalid_predictions'],1)
    def test_accuracy_macro_f1_and_confusions(self):
        result=metrics(scored_rows(self.rows(),self.labels),self.labels)
        self.assertEqual(result['accuracy'],.5)
        self.assertAlmostEqual(result['macro_f1'],1/3)
        self.assertEqual(result['confusions'],[{'expected':self.labels[1],'predicted':self.labels[0],'count':1}])
    def test_candidate_gold_or_text_mismatch_is_rejected(self):
        reference=scored_rows(self.rows(),self.labels)
        for field in ('prompt','expected'):
            candidate=[{**r,'predicted':r['expected']} for r in self.rows()]
            candidate[0][field]='changed'
            with self.assertRaisesRegex(ValueError,'differs'):compare(reference,candidate,self.labels)
    def test_subset_requires_explicit_choice_and_metrics_use_same_rows(self):
        reference=scored_rows(self.rows(),self.labels)
        candidate=[{'id':'b','prediction':self.labels[1]}]
        with self.assertRaisesRegex(ValueError,'ID sets differ'):compare(reference,candidate,self.labels)
        left,right,pairs,scope=compare(reference,candidate,self.labels,True)
        self.assertEqual(len(left),1);self.assertEqual(metrics(left,self.labels)['accuracy'],0)
        self.assertEqual(metrics(right,self.labels)['accuracy'],1)
        self.assertEqual(scope['omitted_reference_rows'],1)
        self.assertEqual(pairs[0]['outcome'],'candidate_only')
    def test_unknown_candidate_and_duplicate_csv_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'unknown'):compare(scored_rows(self.rows(),self.labels),[{'id':'unknown','prediction':self.labels[0]}],self.labels,True)
        with self.assertRaisesRegex(ValueError,'unique'):csv_records('id,predicted\na,x\na,y\n')
    def test_recorded_real_predictions_reproduce_observed_scores(self):
        labels=json.loads((ROOT/'data/categories.json').read_text())
        raw,provenance,_=evaluate.read_archive(ROOT/'data/reference-results.zip',labels)
        self.assertEqual(len(raw),3080)
        reference=scored_rows(raw,labels)
        candidate=[{'id':r['id'],'predicted':r['baseline_predicted']} for r in raw]
        left,right,pairs,scope=compare(reference,candidate,labels)
        self.assertEqual(metrics(left,labels)['correct'],2340)
        self.assertEqual(metrics(right,labels)['correct'],2420)
        self.assertEqual(scope['outcomes']['candidate_only'],483)
        self.assertEqual(scope['outcomes']['reference_only'],403)
        self.assertEqual(provenance['prompt_examples'],77)
    def test_corrupt_dataset_license_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            bad=Path(temporary)/'bad.zip'
            with zipfile.ZipFile(ROOT/'data/reference-results.zip') as source,zipfile.ZipFile(bad,'w') as dest:
                for name in source.namelist():dest.writestr(name,b'wrong license' if name=='DATA_LICENSE' else source.read(name))
            with self.assertRaisesRegex(ValueError,'license'):evaluate.read_archive(bad,json.loads((ROOT/'data/categories.json').read_text()))
    def test_raw_output_has_no_html_or_logo_dependency(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(evaluate,'render',side_effect=AssertionError('UI should not run')):
            output=Path(temporary)/'result'
            self.assertEqual(evaluate.main(['--no-report','--output-dir',str(output)]),0)
            self.assertTrue((output/'scores.json').is_file())
            self.assertFalse((output/'report.html').exists())
            attribution=(output/'DATA_SOURCE.md').read_text()
            self.assertIn('](dataset_provenance.json)',attribution)
            self.assertIn('](DATA_LICENSE)',attribution)
            self.assertEqual(json.loads((output/'dataset_provenance.json').read_text())['test_rows'],3080)
            with zipfile.ZipFile(ROOT/'data/reference-results.zip') as archive:
                self.assertEqual((output/'DATA_LICENSE').read_bytes(),archive.read('DATA_LICENSE'))
    def test_html_escapes_question_text_and_template_is_replaceable(self):
        rows=scored_rows([{**self.rows()[0],'prompt':'<script>alert(1)</script>'}],self.labels)
        summary={'reference':metrics(rows,self.labels),'reference_name':'<model>','comparison':None,'labels':self.labels}
        html=render(summary,rows,None,[],ROOT)
        self.assertNotIn('<script>alert(1)</script>',html)
        with tempfile.TemporaryDirectory() as temporary:
            template=Path(temporary)/'custom.html';template.write_text('<h1>My report</h1>{{cards}}')
            html=render(summary,rows,None,[],ROOT,template)
            self.assertIn('My report',html);self.assertNotIn('Powered by',html)

if __name__=='__main__':unittest.main()
