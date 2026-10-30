import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, Mock
import pymupdf as fitz
import analyzer
import app
from eligibility import evaluate

URL='https://www.gov.si/test.pdf'

class Documents(unittest.TestCase):
    def test_pdf_pages(self):
        with fitz.open() as doc:
            for text in ['The farm must have at least 15 dairy cows.', 'The application must include a business plan.']:
                doc.new_page().insert_text((40,60),text)
            raw=doc.tobytes()
        pages=analyzer.read_pdf(raw)
        self.assertEqual([p['number'] for p in pages],[1,2])
        self.assertIn('business plan',pages[1]['text'])

    def test_corrupt_pdf(self):
        with self.assertRaisesRegex(ValueError,'poškodovan'):
            analyzer.read_pdf(b'%PDF-broken')

    def test_scanned_pdf_ocr_failure(self):
        with fitz.open() as doc:
            doc.new_page();raw=doc.tobytes()
        with patch.object(fitz.Page,'get_textpage_ocr',side_effect=RuntimeError('missing OCR')):
            with self.assertRaisesRegex(ValueError,'OCR ni uspel'):
                analyzer.read_pdf(raw)

    def test_redirect_checked_before_next_request(self):
        response=Mock(status_code=302,headers={'Location':'https://example.org/private'})
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        with patch('analyzer.requests.get',return_value=response) as request:
            with self.assertRaisesRegex(ValueError,'gov.si'):analyzer.get(URL)
        self.assertEqual(request.call_count,1)

class Extraction(unittest.TestCase):
    def setUp(self):
        self.docs=[dict(url=URL,title='Pogoji.pdf',text='At least 15 cows.',pages=1,
                        page_texts=[dict(number=1,text='At least 15 cows.')])]
        self.item=dict(label='Cows',fact_key='cows_min',operator='gte',expected=15,
                       mandatory=True,fixed=False,evidence_url=URL,
                       evidence_quote='At least 15 cows.',explanation='Minimum')

    def response(self, content):
        return Mock(ok=True,json=lambda:dict(choices=[dict(message=dict(content=content))]))

    def test_missing_key(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':''}):
            with self.assertRaisesRegex(ValueError,'API ključ ni nastavljen'):analyzer.ai_extract(self.docs)

    def test_structured_evidence_and_page(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}), patch('analyzer.requests.post',return_value=self.response(json.dumps({'conditions':[self.item]}))):
            result=analyzer.ai_extract(self.docs)
        self.assertEqual(result[0]['page_number'],1)
        self.assertEqual(result[0]['document_title'],'Pogoji.pdf')

    def test_invented_quote_rejected(self):
        self.item['evidence_quote']='Invented condition'
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}), patch('analyzer.requests.post',return_value=self.response(json.dumps({'conditions':[self.item]}))):
            with self.assertRaisesRegex(ValueError,'citata'):analyzer.ai_extract(self.docs)

    def test_invalid_json(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}), patch('analyzer.requests.post',return_value=self.response('not json')):
            with self.assertRaisesRegex(ValueError,'veljavnih'):analyzer.ai_extract(self.docs)

    def test_failed_attachment_prevents_partial_analysis(self):
        with patch('analyzer.collect',return_value=(self.docs,['PDF ni dosegljiv'],1)), patch('analyzer.ai_extract') as ai:
            with self.assertRaisesRegex(ValueError,'PDF ni dosegljiv'):analyzer.analyze(URL)
            ai.assert_not_called()

class Eligibility(unittest.TestCase):
    def test_intervals(self):
        for minimum,expected in [(15,'met'),(40,'unknown'),(60,'unmet_changeable')]:
            with self.subTest(minimum=minimum):
                self.assertEqual(evaluate(dict(fact_key='cows_min',operator='gte',expected=minimum),{'cows_min':20,'cows_max':50}),expected)

    def test_unknown_and_reference_date(self):
        rule=dict(fact_key='omd_points',operator='gte',expected=100)
        self.assertEqual(evaluate(rule,{}),'unknown')
        self.assertEqual(evaluate({**rule,'reference_date':'2023-12-31'},{'omd_points':200}),'manual_review')

class Persistence(unittest.TestCase):
    def test_migration_preserves_existing_database_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'test.sqlite3'
            source=sqlite3.connect(app.ROOT/'kmetrazpisi.sqlite3')
            target=sqlite3.connect(db);source.backup(target);source.close()
            tables=[r[0] for r in target.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
            before={t:target.execute('select * from '+t).fetchall() for t in tables};target.close()
            with patch.object(app,'DB',db):
                app.init();app.init()
                with app.conn() as c:
                    for table,rows in before.items():
                        after=[tuple(r)[:len(rows[0])] for r in c.execute('select * from '+table)] if rows else []
                        if table!='settings':self.assertEqual(after,rows,table)
                    self.assertEqual(c.execute('pragma integrity_check').fetchone()[0],'ok')

    def test_analysis_persists_page_and_failure_preserves_previous_result(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app,'DB',Path(tmp)/'test.sqlite3'):
            app.init()
            with app.conn() as c:
                tid=c.execute("insert into tenders(title,url) values('test',?)",(URL,)).lastrowid
            item=dict(label='Cows',fact_key='cows_min',operator='gte',expected=15,mandatory=True,fixed=False,evidence_url=URL,evidence_quote='15 cows',explanation='minimum',document_title='Test.pdf',page_number=2)
            result=dict(conditions=[item],digest='hash',mode='AI',documents=[],warnings=[],pdf_links_found=1)
            with patch('app.analyze',return_value=result):app.analyze_tender(tid)
            with patch('app.analyze',side_effect=ValueError('API failure')):
                with self.assertRaises(ValueError):app.analyze_tender(tid)
            automatic=app.automated_assessment(tid,app.DEFAULT)
            self.assertEqual(automatic['conditions'][0]['page_number'],2)
            self.assertEqual(automatic['conditions'][0]['result'],'met')
            self.assertFalse(automatic['auto_hide'])

if __name__=='__main__':unittest.main()

class HTTPWorkflow(unittest.TestCase):
    def test_routes_and_analysis_diagnostics(self):
        import threading
        import requests
        from http.server import ThreadingHTTPServer
        with tempfile.TemporaryDirectory() as tmp, patch.object(app,'DB',Path(tmp)/'http.sqlite3'):
            app.init()
            server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base='http://127.0.0.1:'+str(server.server_port)
            try:
                page=requests.get(base,timeout=5)
                self.assertEqual(page.status_code,200)
                self.assertIn('Različica '+app.VERSION,page.text)
                self.assertNotIn('{{APP_VERSION}}',page.text)
                state=requests.get(base+'/api/state',timeout=5).json()
                self.assertEqual(state['version'],app.VERSION)
                self.assertIsInstance(state['ai_configured'],bool)
                self.assertEqual(requests.get(base+'/api/state',timeout=5).json()['farm']['municipality'],'Ivančna Gorica')
                url='https://www.gov.si/zbirke/javne-objave/javni-razpis-test/'
                with patch('app.listed_call',return_value=True):
                    self.assertEqual(requests.post(base+'/api/tenders',json={'url':url,'title':'Test'},timeout=5).status_code,200)
                tid=requests.get(base+'/api/state',timeout=5).json()['tenders'][0]['id']
                with patch('app.analyze',side_effect=ValueError('API ključ ni nastavljen')):
                    response=requests.post(base+f'/api/tender/{tid}/analyze',json={},timeout=5)
                self.assertEqual(response.status_code,400)
                self.assertIn('API ključ ni nastavljen',response.json()['error'])
            finally:
                server.shutdown();server.server_close();thread.join()

class SKPDiscovery(unittest.TestCase):
    URL='https://www.gov.si/zbirke/javne-objave/javni-razpis-za-podintervencijo-nalozbe-kmetij-v-okviru-intervencije-nalozbe-v-prilagoditev-na-podnebne-spremembe-pri-trajnih-nasadih-za-leto-2026/'

    def listing(self):
        return f'''<header><a href="/zbirke/javne-objave/javni-razpis-drugo/">Javni razpis drugo</a></header>
        <main><a href="{self.URL}">Javni razpis za podintervencijo Naložbe kmetij</a>
        <a href="{app.SKP_PREFIX}navodila/">Navodila za javni razpis</a>
        <a href="/zbirke/javne-objave/navodila/">Navodila</a>
        <a href="https://evil.example/zbirke/javne-objave/javni-razpis/">Javni razpis</a></main>'''.encode()

    def test_only_calls_from_skp_content(self):
        import skp
        self.assertEqual(list(skp.discover(self.listing())),[self.URL])
        with patch('skp.get',return_value=(skp.SOURCE_URL,self.listing(),'text/html')):
            self.assertTrue(skp.listed_call(self.URL))
            self.assertFalse(skp.listed_call('https://www.gov.si/zbirke/javne-objave/javni-razpis-drugo/'))

    def test_scan_repeatability_and_no_data_deletion(self):
        import skp
        with tempfile.TemporaryDirectory() as tmp, patch.object(app,'DB',Path(tmp)/'scan.sqlite3'), patch('app.notify'):
            app.init()
            with app.conn() as c:c.execute("insert into tenders(title,url,source) values('Old information',?,'GOV.SI – SKP')",(app.SKP_PREFIX+'navodila/',))
            with patch('skp.get',return_value=(skp.SOURCE_URL,self.listing(),'text/html')):
                self.assertEqual(app.scan()[0]['new'],1)
                self.assertEqual(app.scan()[0]['new'],0)
            with app.conn() as c:
                self.assertEqual(c.execute('select count(*) from tenders').fetchone()[0],2)
                self.assertEqual(c.execute('select count(*) from tenders where url=?',(self.URL,)).fetchone()[0],1)

    def test_collect_pdf_from_call(self):
        pdf_url='https://www.gov.si/assets/test/razpis.pdf'
        html=f'<main><a href="{pdf_url}">Razpisna dokumentacija</a></main>'.encode()
        with fitz.open() as doc:
            doc.new_page().insert_text((40,60),'The farm must have at least 15 dairy cows.');pdf=doc.tobytes()
        with patch('analyzer.get',side_effect=[(self.URL,html,'text/html'),(pdf_url,pdf,'application/pdf')]):
            docs,errors,count=analyzer.collect(self.URL)
        self.assertEqual(errors,[])
        self.assertEqual(count,1)
        self.assertEqual(docs[1]['page_texts'][0]['number'],1)

class LongDocuments(unittest.TestCase):
    def test_reads_beyond_old_150_page_limit(self):
        with fitz.open() as document:
            for number in range(1, 153):
                document.new_page().insert_text((40,60),f'Page {number}: The farm must submit required evidence.')
            raw=document.tobytes()
        pages=analyzer.read_pdf(raw)
        self.assertEqual(len(pages),152)
        self.assertIn('Page 152:',pages[-1]['text'])

    def document(self):
        pages=[{'number':n,'text':f'Condition on original page {n}. '+('Farm data. '*600)} for n in range(1,153)]
        return dict(url=URL,title='Long.pdf',pages=152,page_texts=pages,text='\n'.join(p['text'] for p in pages))

    def test_all_pages_covered_and_requests_bounded(self):
        doc=self.document()
        chunks=list(analyzer.document_chunks([doc]))
        self.assertGreater(len(chunks),1)
        self.assertEqual({p['number'] for c in chunks for p in c['page_texts']},set(range(1,153)))
        for chunk in chunks:
            self.assertLessEqual(len(chunk['page_texts']),10)
            self.assertLess(len(chunk['text']),25000)
        self.assertEqual(chunks[0]['page_texts'][-1]['number'],chunks[1]['page_texts'][0]['number'])

    def test_oversize_page_is_not_truncated(self):
        text='A'*25000+'MIDDLE'+'B'*25000+'FINAL'
        doc=dict(url=URL,title='Long page',pages=1,page_texts=[dict(number=151,text=text)],text=text)
        chunks=list(analyzer.document_chunks([doc]))
        self.assertTrue(any('MIDDLE' in c['text'] for c in chunks))
        self.assertTrue(any('FINAL' in c['text'] for c in chunks))
        self.assertTrue(all(c['page_texts'][0]['number']==151 for c in chunks))

    def test_merge_preserves_late_page_and_removes_overlap_duplicates(self):
        item=dict(label='Requirement',fact_key='unknown',operator='none',expected=None,mandatory=False,fixed=False,evidence_url=URL,evidence_quote='Unique quote',explanation='Review',page_number=151,document_title='Long.pdf')
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}), patch('analyzer._ai_extract_chunk',return_value=[item]) as extract:
            result=analyzer.ai_extract([self.document()])
        self.assertGreater(extract.call_count,1)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['page_number'],151)

    def test_later_chunk_failure_reports_progress_instead_of_partial_result(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}), patch('analyzer._ai_extract_chunk',side_effect=[[],ValueError('HTTP 429')]):
            with self.assertRaisesRegex(ValueError,r'sklop 2/.*Long.pdf.*HTTP 429'):
                analyzer.ai_extract([self.document()])

class EvidenceRepair(unittest.TestCase):
    def test_pdf_typography_without_fuzzy_matching(self):
        self.assertEqual(analyzer.normalize_quote('kme-\ntija ima ﬁnančno pod\u00adporo'),analyzer.normalize_quote('kmetija ima finančno podporo'))
        self.assertNotEqual(analyzer.normalize_quote('najmanj 15 krav'),analyzer.normalize_quote('najmanj 50 krav'))

    def test_one_repair_request_preserves_validated_result(self):
        doc=dict(url=URL,title='Test',text='Exact source',pages=None)
        item=dict(label='Test',fact_key='unknown',operator='none',expected=None,mandatory=False,fixed=False,evidence_url=URL,evidence_quote='Exact source',explanation='Review',page_number=None)
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}), patch('analyzer._ai_extract_chunk',side_effect=[analyzer.EvidenceError('Invalid quote'),[item]]) as extract:
            self.assertEqual(analyzer.ai_extract([doc]),[item])
            self.assertEqual(extract.call_count,2)
            self.assertEqual(extract.call_args.kwargs['evidence_feedback'],'Invalid quote')

    def test_repair_is_bounded(self):
        doc=dict(url=URL,title='Test',text='Exact source',pages=None)
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}), patch('analyzer._ai_extract_chunk',side_effect=analyzer.EvidenceError('Invalid quote')) as extract:
            with self.assertRaisesRegex(ValueError,'sklop 1/1'):
                analyzer.ai_extract([doc])
            self.assertEqual(extract.call_count,2)

    def test_repair_still_rejects_invented_quote(self):
        case=Extraction();case.setUp()
        case.item['evidence_quote']='This sentence does not exist in source'
        response=case.response(json.dumps({'conditions':[case.item]}))
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}), patch('analyzer.requests.post',return_value=response) as request:
            with self.assertRaisesRegex(ValueError,'citata ni mogoče potrditi'):
                analyzer.ai_extract(case.docs)
            self.assertEqual(request.call_count,2)
