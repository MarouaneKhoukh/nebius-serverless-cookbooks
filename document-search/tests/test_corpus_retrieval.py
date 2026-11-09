"""Offline corpus provenance, safe preparation and diagnostic scoring checks."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from corpus import archive_members, prepare, sha256
from embed import RecipeError, check_queries, digest, index_collection, load_chunks, read_json, report
from retrieval import BM25, load_queries, source_metrics


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output, self.cache = self.root/'documents',self.root/'cache'
        members={'doc/library/json.txt':b'JSON encoder and decoder.\n\nRead a JSON file safely.\n',
                 'doc/library/socket.txt':b'Socket network connections.\n\nConnect a TCP socket.\n',
                 'doc/license.txt':b'Test license retained verbatim.\n'}
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
            for name,data in members.items():z.writestr(name,data)
        self.archive=stream.getvalue()
        self.source={'dataset':'test documentation','version':'fixture','archive':{'url':'https://example.org/docs.zip','sha256':sha256(self.archive),'bytes':len(self.archive),'type':'zip','format':'text'},
                     'license':{'name':'fixture only','member':'doc/license.txt','sha256':sha256(members['doc/license.txt'])},
                     'documents':[{'path':name.removeprefix('doc/'),'member':name,'sha256':sha256(data),'title':name,'url':'https://example.org/'+name} for name,data in members.items() if name!='doc/license.txt']}
        self.source_path=self.root/'source.json'
        self.save_source()

    def save_source(self):
        self.source_path.write_text(json.dumps(self.source))

    def prepare(self, fetch=None):
        return prepare(self.output,self.cache,source_path=self.source_path,fetch=fetch or (lambda url:self.archive))

    def test_verified_corpus_license_and_sources_survive_a_cached_rerun(self):
        first=self.prepare()
        chunks=load_chunks(self.output)
        self.assertEqual(len(chunks),2)
        self.assertTrue(all(c['source_url'].startswith('https://') for c in chunks))
        self.assertEqual((self.output/'DATA_LICENSE').read_bytes(),b'Test license retained verbatim.\n')
        self.assertEqual(first,self.prepare(lambda url:self.fail('verified archive should be cached')))
        self.assertEqual(chunks,load_chunks(self.output))

    def test_wrong_archive_hash_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError,'checksum'):
            self.prepare(lambda url:b'wrong source')
        self.assertFalse((self.output/'.corpus.json').exists())

    def test_wrong_document_hash_leaves_no_complete_manifest(self):
        self.source['documents'][1]['sha256']='0'*64;self.save_source()
        with self.assertRaisesRegex(ValueError,'document checksum'):self.prepare()
        self.assertFalse((self.output/'.corpus.json').exists())

    def test_other_user_documents_are_preserved(self):
        self.output.mkdir();own=self.output/'my-notes.txt';own.write_text('keep this')
        with self.assertRaisesRegex(ValueError,'other documents'):self.prepare()
        self.assertEqual(own.read_text(),'keep this')

    def test_symlinked_destination_directory_is_rejected(self):
        self.output.mkdir();outside=self.root/'outside';outside.mkdir()
        (self.output/'library').symlink_to(outside,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlinked'):self.prepare()
        self.assertEqual(list(outside.iterdir()),[])

    def test_archive_missing_or_duplicate_members_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'every pinned'):
            archive_members(self.archive,{'not-present.txt'},'zip')
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr('same.txt','first')
            with self.assertWarns(UserWarning):z.writestr('same.txt','second')
        with self.assertRaisesRegex(ValueError,'duplicate'):
            archive_members(stream.getvalue(),{'same.txt'},'zip')

    def test_modified_prepared_text_cannot_silently_reuse_vectors(self):
        self.prepare();(self.output/'library/json.txt').write_text('changed')
        with self.assertRaisesRegex(RecipeError,'checksum changed'):load_chunks(self.output)

    def test_unknown_prepared_source_is_rejected(self):
        self.prepare();(self.output/'extra.txt').write_text('extra')
        with self.assertRaisesRegex(RecipeError,'corpus files changed'):load_chunks(self.output)


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.docs=self.root/'docs';self.docs.mkdir()
        (self.docs/'json.txt').write_text('JSON encoder decoder. Parse a JSON document.')
        (self.docs/'socket.txt').write_text('Network socket connection. Connect a TCP socket.')
        self.chunks=load_chunks(self.docs)

    def test_bm25_ranks_literal_matching_passages_and_ties_stably(self):
        index=BM25(self.chunks)
        self.assertEqual(index.search('JSON decoder')[0]['source'],'json.txt')
        self.assertEqual(index.search('TCP socket')[0]['source'],'socket.txt')
        self.assertEqual([r['id'] for r in index.search('unseenword')],sorted(c['id'] for c in self.chunks))

    def test_check_queries_embeds_all_questions_and_compares_the_same_sources(self):
        output=self.root/'results'
        settings={'model':'fixture-model','model_revision':'fixture','dimensions':2,'chunk_words':160}
        vectors={'JSON encoder decoder. Parse a JSON document.':[1.,0.], 'Network socket connection. Connect a TCP socket.':[0.,1.]}
        index_collection(self.chunks,output,settings,lambda texts,*args:[vectors[t] for t in texts])
        queries=self.root/'queries.json';queries.write_text(json.dumps({'description':'fixture checks','queries':[{'id':'q1','text':'JSON decoder','expected_sources':['json.txt']},{'id':'q2','text':'TCP socket','expected_sources':['socket.txt']}]}))
        class Endpoint:
            def ready(self,model):self.model=model
            def embed(self,texts,*args):
                self.texts=texts
                return [[1.,0.],[0.,1.]]
        endpoint=Endpoint();summary=check_queries(output,queries,endpoint,top_k=2)
        self.assertEqual(len(endpoint.texts),2)
        self.assertTrue(all(text.startswith('Instruct:') for text in endpoint.texts))
        self.assertEqual(summary['semantic']['hit_at_1'],1.)
        self.assertEqual(summary['bm25']['hit_at_1'],1.)
        self.assertEqual(summary['query_provenance']['description'],'fixture checks')
        self.assertEqual(len(read_json(output/'retrieval-checks.json')['results']),2)

    def test_unknown_expected_source_does_not_create_a_quality_score(self):
        p=self.root/'queries.json';p.write_text(json.dumps({'queries':[{'id':'q','text':'question','expected_sources':['absent.txt']}]}))
        with self.assertRaisesRegex(ValueError,'present in this corpus'):load_queries(p,{'json.txt'})

    def test_source_checks_do_not_treat_any_returned_result_as_correct(self):
        self.assertEqual(source_metrics([{'source':'wrong.txt'}],['json.txt']),{'hit_at_1':False,'hit_at_k':False,'reciprocal_rank_at_k':0.})
        self.assertEqual(source_metrics([{'source':'wrong.txt'},{'source':'json.txt'}],['json.txt'])['reciprocal_rank_at_k'],.5)

    def test_report_links_only_safe_source_urls_and_escapes_text(self):
        p=self.root/'report.html'
        report(p,'test','summary',['source'],[{'source':'<script>bad</script>','source_url':'javascript:alert(1)'}])
        self.assertNotIn('href=',p.read_text());self.assertIn('&lt;script&gt;',p.read_text())
        report(p,'test','summary',['source'],[{'source':'json.txt','source_url':'https://docs.python.org/3/library/json.html'}])
        self.assertIn('href="https://docs.python.org/3/library/json.html"',p.read_text())


if __name__=='__main__':unittest.main()
