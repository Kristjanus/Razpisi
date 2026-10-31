import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
import requests
from http.server import ThreadingHTTPServer
import app
import legal_explainer as legal
from law_documents import LawLibrary,decode_document,parse_law,document_metadata

URL='https://pisrs.si/api/datoteke/integracije/493126267'
RAW=(Path(__file__).parent/'fixtures'/'ured8874_npb5_excerpt.html').read_bytes()


def response(raw=RAW):
    result=Mock(status_code=200,headers={'content-type':'text/html'},iter_content=lambda size:[raw])
    result.__enter__=Mock(return_value=result);result.__exit__=Mock(return_value=False)
    return result


def store(library,raw=RAW):
    text,kind=decode_document(raw);metadata=document_metadata(raw)
    return library.store(URL,raw,text,kind,parse_law(text),metadata['version_label'],metadata=metadata)

class LawRegistry(unittest.TestCase):
    def test_import_actual_export_then_reuse_without_download(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'KMETRAZPISI_LAW_DB':str(Path(tmp)/'laws.sqlite3')}):
            with patch('legal_explainer.requests.get',return_value=response()) as download:
                result=legal.import_law_url(URL)
                again=legal.import_law_url(URL)
            self.assertEqual(download.call_count,1)
            self.assertEqual(result['entries'][0]['source_id'],'URED8874')
            self.assertEqual(again['entries'][0]['source_url'],URL)
            self.assertEqual(len(LawLibrary().entries()),1)

    def test_refresh_preserves_old_content_and_does_not_choose_ambiguous_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            library=LawLibrary(Path(tmp)/'laws.sqlite3')
            old=store(library)
            new=store(library,RAW.replace(b'NPB5',b'NPB6').replace('besedilo št. 5'.encode(),'besedilo št. 6'.encode()))
            self.assertNotEqual(old,new)
            self.assertEqual(len(library.entries()),2)
            self.assertIsNone(library.find_url(URL))
            self.assertIn('5',library.load(URL,old)['metadata']['version_label'])

    def test_saved_reference_skips_search_but_explains_selected_article(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'KMETRAZPISI_LAW_DB':str(Path(tmp)/'laws.sqlite3'),'OPENAI_API_KEY':'test'}):
            library=LawLibrary();store(library)
            condition={'evidence_quote':'Izpolnjuje pogoje iz 9. člena uredbe.','_legal_context_key':'documents-sha-1'}
            key=hashlib.sha256((condition['_legal_context_key']+'\n'+condition['evidence_quote']).encode()).hexdigest()
            library.remember_binding(key,[{'law_title':'Uredba o skupnih določbah','provision':'9. člen','source_url':URL}])
            quote='ni izključen iz prejemanja podpore v skladu z zakonom, ki ureja kmetijstvo;'
            reply=Mock(ok=True,json=lambda:{'choices':[{'message':{'content':json.dumps({'explanation':'Vlagatelj ne sme biti izključen iz prejemanja podpore.','source_quote':quote,'version_note':'Preverite časovno uporabo.'})}}]})
            with patch('legal_explainer.requests.post',return_value=reply) as ai,patch('legal_explainer.requests.get') as download:
                result=legal.explain(condition,'context')
            self.assertEqual(result['status'],'explained')
            self.assertTrue(result['provisions'][0]['local_snapshot'])
            self.assertEqual(ai.call_count,1)
            self.assertTrue(ai.call_args.args[0].endswith('/chat/completions'))
            selected=json.loads(ai.call_args.kwargs['json']['messages'][1]['content'])['selected_articles']
            self.assertNotIn('12. člen',selected)
            download.assert_not_called()
            self.assertIsNone(library.binding(hashlib.sha256(('documents-sha-2\n'+condition['evidence_quote']).encode()).hexdigest()))

    def test_unofficial_import_is_rejected_without_network(self):
        with patch('legal_explainer.requests.get') as download:
            with self.assertRaises(ValueError):legal.import_law_url('https://example.org/fake-law')
        download.assert_not_called()

    def test_registry_http_import_and_list(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'KMETRAZPISI_LAW_DB':str(Path(tmp)/'laws.sqlite3')}):
            server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                self.assertEqual(requests.get(base+'/api/laws',timeout=5).json()['entries'],[])
                with patch('legal_explainer.requests.get',return_value=response()):
                    imported=requests.post(base+'/api/laws/import',json={'url':URL},timeout=5)
                self.assertEqual(imported.status_code,200)
                listed=requests.get(base+'/api/laws',timeout=5).json()['entries']
                self.assertEqual(listed[0]['source_id'],'URED8874')
                self.assertFalse(listed[0]['version_verified_for_tender'])
            finally:server.shutdown();server.server_close();thread.join()
