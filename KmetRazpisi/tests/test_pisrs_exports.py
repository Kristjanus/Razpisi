import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import legal_explainer as legal
from pisrs_exports import resolve_export
from law_documents import LawParseError,LawLibrary
from tender_sources import load_prescribed

RECORD='https://www.pisrs.si/Pis.web/pregledPredpisa?id=URED9278'
EXPORT='https://pisrs.si/api/datoteke/integracije/545935768'


def synthetic_export(identifier='URED9278'):
    # Synthetic structural sample, not the content of the actual regulation.
    return f'<html><title>{identifier} NPB1</title><p class="naslov">Testni predpis za preverjanje identitete</p><p class="npb">NPB1</p><p class="clen">1. člen</p><p>(1) Vlagatelj mora izpolniti testni pogoj, uporabljen samo v testu.</p></html>'.encode()


def response(raw):
    r=Mock(status_code=200,headers={'content-type':'text/html'},iter_content=lambda size:[raw])
    r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=False)
    return r

class PISRSExports(unittest.TestCase):
    def test_user_supplied_url_is_used_instead_of_record_page(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'KMETRAZPISI_LAW_DB':str(Path(tmp)/'laws.sqlite3')}):
            with patch('legal_explainer.requests.get',return_value=response(synthetic_export())) as download:
                text=legal.source_text(RECORD)
            self.assertEqual(download.call_args.args[0],EXPORT)
            self.assertIn('testni pogoj',text)
            entry=LawLibrary().entries()[0]
            self.assertEqual(entry['source_id'],'URED9278')
            self.assertEqual(entry['resolved_url'],EXPORT)
            with patch('legal_explainer.requests.get') as again:
                self.assertEqual(legal.source_text(RECORD),text)
            again.assert_not_called()

    def test_wrong_export_id_is_rejected_not_saved(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'KMETRAZPISI_LAW_DB':str(Path(tmp)/'laws.sqlite3')}),patch('legal_explainer.requests.get',return_value=response(synthetic_export('URED0000'))):
            with self.assertRaisesRegex(LawParseError,'ne potrjuje'):legal.source_text(RECORD)
            self.assertEqual(LawLibrary().entries(),[])

    def test_unknown_ids_are_not_guessed(self):
        url='https://www.pisrs.si/Pis.web/pregledPredpisa?id=PRAV15604'
        self.assertEqual(resolve_export(url), (url,'PRAV15604'))
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'KMETRAZPISI_LAW_DB':str(Path(tmp)/'laws.sqlite3')}),patch('legal_explainer.requests.get',return_value=response(b'<html><div id="app"></div></html>')):
            with self.assertRaisesRegex(LawParseError,'vmesnik PISRS'):legal.source_text(url)

    def test_explicit_html_link_can_be_followed_without_inventing_file_id(self):
        url='https://pisrs.si/pregledPredpisa?id=PRAV12345';target='https://pisrs.si/api/datoteke/integracije/123456789'
        page=f'<html><div id="app"></div><a href="{target}">HTML</a></html>'.encode()
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'KMETRAZPISI_LAW_DB':str(Path(tmp)/'laws.sqlite3')}),patch('legal_explainer.requests.get',side_effect=[response(page),response(synthetic_export('PRAV12345'))]) as download:
            legal.source_text(url)
            self.assertEqual(download.call_count,2)
            self.assertEqual(download.call_args.args[0],target)

    def test_supplied_law_catalog_receives_downloaded_structured_law(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'KMETRAZPISI_LAW_DB':str(Path(tmp)/'laws.sqlite3')}),patch('legal_explainer.requests.get',return_value=response(synthetic_export())):
            docs,warnings=load_prescribed([{'title':'Uredba o naložbah','url':RECORD}])
        self.assertEqual(warnings,[])
        self.assertEqual(docs[0]['url'],EXPORT)
        self.assertIn('1',docs[0]['law']['articles'])
