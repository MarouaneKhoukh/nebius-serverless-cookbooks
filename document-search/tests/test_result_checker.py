"""Validate exported collections, including wrong joins and incomplete work."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from embed import DIMENSIONS,MODEL,RecipeError,index_collection,load_chunks
spec=importlib.util.spec_from_file_location('check_document_result',ROOT/'scripts/check_result.py')
checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)


class ResultCheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.docs=self.root/'docs';self.docs.mkdir()
        (self.docs/'a.txt').write_text('First document about a queue.')
        (self.docs/'b.txt').write_text('Second document about a socket.')
        self.chunks=load_chunks(self.docs);self.output=self.root/'results'
        self.settings={'model':MODEL,'model_revision':'offline-fixture','dimensions':DIMENSIONS,'chunk_words':160}
        self.embed=lambda texts,*args:[[1.]+[0.]*(DIMENSIONS-1) for t in texts]

    def test_a_complete_aligned_collection_passes(self):
        index_collection(self.chunks,self.output,self.settings,self.embed)
        result=checker.verify(self.docs,self.output)
        self.assertTrue(result['complete']);self.assertEqual(result['chunks_saved'],2)

    def test_incomplete_work_is_not_reported_as_complete(self):
        index_collection(self.chunks,self.output,self.settings,self.embed,limit=1)
        with self.assertRaisesRegex(RecipeError,'incomplete'):checker.verify(self.docs,self.output)

    def test_changed_exported_source_text_is_rejected(self):
        index_collection(self.chunks,self.output,self.settings,self.embed)
        p=self.output/'metadata.jsonl';rows=[json.loads(l) for l in p.read_text().splitlines()]
        rows[0]['text']='changed source'
        p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        with self.assertRaisesRegex(ValueError,'metadata differs'):checker.verify(self.docs,self.output)

    def test_reordered_vector_export_is_rejected(self):
        index_collection(self.chunks,self.output,self.settings,self.embed)
        p=self.output/'vectors.jsonl';rows=p.read_text().splitlines();p.write_text('\n'.join(reversed(rows))+'\n')
        with self.assertRaisesRegex(ValueError,'reordered'):checker.verify(self.docs,self.output)


if __name__=='__main__':unittest.main()
