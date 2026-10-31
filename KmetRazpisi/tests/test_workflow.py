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
            with self.assertRaisesRegex(ValueError,'Noben pogoj'):
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

class PartialEvidence(unittest.TestCase):
    def test_invalid_web_quote_does_not_block_valid_pdf(self):
        web=dict(url='https://www.gov.si/page',title='Uradna spletna objava',text='Web text',pages=None)
        pdf=dict(url=URL,title='Rules.pdf',text='At least 15 cows.',pages=1,page_texts=[dict(number=7,text='At least 15 cows.')])
        item=dict(label='Cows',fact_key='cows_min',operator='gte',expected=15,mandatory=True,fixed=False,evidence_url=URL,evidence_quote='At least 15 cows.',explanation='Minimum',page_number=7)
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}), patch('analyzer._ai_extract_chunk',side_effect=[analyzer.EvidenceError('Invalid web quote'),analyzer.EvidenceError('Invalid web quote'),[item]]):
            result=analyzer.ai_extract([web,pdf])
        self.assertEqual(result,[item])
        self.assertIn('NEPOPOLNA ANALIZA',result.warnings[0])
        self.assertIn('Uradna spletna objava',result.warnings[0])

    def test_mixed_conditions_keep_only_valid_quotes(self):
        case=Extraction();case.setUp()
        bad={**case.item,'label':'Invented','evidence_quote':'Not in source'}
        response=case.response(json.dumps({'conditions':[case.item,bad]}))
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}), patch('analyzer.requests.post',return_value=response):
            result=analyzer.ai_extract(case.docs)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['evidence_quote'],'At least 15 cows.')
        self.assertTrue(result.warnings)

    def test_analyze_exposes_partial_warning(self):
        results=analyzer.ExtractionResults();results.append({'label':'Verified'})
        results.warnings=['NEPOPOLNA ANALIZA: missing web evidence']
        docs=[dict(url=URL,title='PDF',pages=1,text='source')]
        with patch('analyzer.collect',return_value=(docs,[],1)),patch('analyzer.ai_extract',return_value=results):
            result=analyzer.analyze(URL)
        self.assertIn(results.warnings[0],result['warnings'])

class AnalysisProgress(unittest.TestCase):
    def wait_finished(self, tid):
        import time
        import analysis_jobs
        end=time.monotonic()+3
        while time.monotonic()<end:
            job=analysis_jobs.status(tid)
            if job['status']!='running':return job
            time.sleep(.01)
        self.fail('Analysis worker did not finish')

    def test_background_progress_duplicate_start_and_completion(self):
        import analysis_jobs
        import threading
        entered=threading.Event();release=threading.Event()
        calls=[]
        def worker(tid,progress):
            calls.append(tid);progress(50,'AI: sklop 2/4');entered.set()
            release.wait(3)
            return {'count':2}
        with patch.dict(analysis_jobs._jobs,{},clear=True):
            try:
                analysis_jobs.start(123,worker)
                self.assertTrue(entered.wait(2))
                job=analysis_jobs.start(123,worker)
                self.assertEqual(job['percent'],50)
                self.assertEqual(job['message'],'AI: sklop 2/4')
                self.assertEqual(calls,[123])
            finally:release.set()
            job=self.wait_finished(123)
            self.assertEqual(job['status'],'done')
            self.assertEqual(job['percent'],100)
            self.assertEqual(job['result']['count'],2)

    def test_failure_does_not_claim_100_percent(self):
        import analysis_jobs
        def worker(tid,progress):
            progress(45,'AI');raise ValueError('HTTP 429')
        with patch.dict(analysis_jobs._jobs,{},clear=True):
            analysis_jobs.start(124,worker)
            job=self.wait_finished(124)
            self.assertEqual(job['status'],'failed')
            self.assertEqual(job['percent'],45)
            self.assertIn('HTTP 429',job['error'])

    def test_actual_chunk_callbacks(self):
        doc=LongDocuments().document();events=[]
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch('analyzer._ai_extract_chunk',return_value=[]):
            analyzer.ai_extract([doc],progress=lambda p,m:events.append((p,m)))
        count=len(list(analyzer.document_chunks([doc])))
        self.assertEqual(len(events),count)
        self.assertIn(f'sklop {count}/{count}',events[-1][1])
        self.assertEqual([p for p,m in events],sorted(p for p,m in events))

    def test_async_http_routes(self):
        import threading
        import requests
        import analysis_jobs
        from http.server import ThreadingHTTPServer
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'DB',Path(tmp)/'progress.sqlite3'),patch.dict(analysis_jobs._jobs,{},clear=True):
            app.init()
            with app.conn() as c:tid=c.execute("insert into tenders(title,url) values('Test',?)",(URL,)).lastrowid
            server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}/api/tender/{tid}'
            entered=threading.Event();release=threading.Event()
            def worker(tid,progress):
                progress(65,'AI: sklop 3/5');entered.set();release.wait(3)
                return {'count':1}
            try:
                with patch('app.analyze_tender',side_effect=worker):
                    response=requests.post(base+'/analyze-start',json={},timeout=5)
                    self.assertEqual(response.status_code,202)
                    self.assertTrue(entered.wait(2))
                    job=requests.get(base+'/analysis-progress',timeout=5).json()
                    self.assertEqual(job['status'],'running')
                    self.assertEqual(job['percent'],65)
                    release.set();self.wait_finished(tid)
                    self.assertEqual(requests.get(base+'/analysis-progress',timeout=5).json()['status'],'done')
            finally:
                release.set();server.shutdown();server.server_close();thread.join()

class MinimumPoints(unittest.TestCase):
    def test_explicit_threshold_is_separate_from_farm_eligibility(self):
        quote='Vloga mora doseči najmanj 30 točk.'
        docs=[dict(url=URL,title='Razpis',pages=1,text=quote,page_texts=[dict(number=12,text=quote)])]
        item=dict(label='Minimalni prag za sklop A',fact_key='minimum_selection_points',operator='gte',expected=30,mandatory=True,fixed=True,evidence_url=URL,evidence_quote=quote,explanation='Velja za sklop A.')
        case=Extraction();response=case.response(json.dumps({'conditions':[item]}))
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch('analyzer.requests.post',return_value=response):
            result=analyzer.ai_extract(docs)
        self.assertEqual(result[0]['expected'],30)
        self.assertEqual(result[0]['page_number'],12)
        self.assertFalse(result[0]['mandatory'])
        self.assertFalse(result[0]['fixed'])
        self.assertEqual(evaluate(result[0],{'minimum_selection_points':100}),'manual_review')

    def test_invalid_threshold_is_rejected(self):
        case=Extraction();case.setUp()
        case.item.update(fact_key='minimum_selection_points',expected=-10)
        response=case.response(json.dumps({'conditions':[case.item]}))
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch('analyzer.requests.post',return_value=response):
            with self.assertRaisesRegex(ValueError,'neveljaven minimalni prag'):
                analyzer.ai_extract(case.docs)

    def test_invented_threshold_without_source_quote_is_not_accepted(self):
        case=Extraction();case.setUp()
        case.item.update(fact_key='minimum_selection_points',expected=30,evidence_quote='At least 30 points.')
        response=case.response(json.dumps({'conditions':[case.item]}))
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch('analyzer.requests.post',return_value=response):
            with self.assertRaisesRegex(ValueError,'Noben pogoj'):
                analyzer.ai_extract(case.docs)

class CriteriaSelection(unittest.TestCase):
    def fixture(self):
        from scoring_scope import annotate_pages
        pages=[dict(number=i,text=f'Text on page {i}') for i in range(1,31)]
        annotate_pages(pages,[[1,'Skupna pravila',1],[1,'IRP01',3],[1,'IRP02',10],[1,'Skupne opombe',29]])
        primary=dict(url='https://www.gov.si/call',title='Razpis',text='Za izbor se uporabljajo merila IRP01.',pages=None)
        criteria=dict(url=URL,title='Merila za izbor operacij',text='all',page_texts=pages,pages=30)
        return primary,criteria

    def test_bookmarked_section_and_common_pages(self):
        from scoring_scope import select_documents
        primary,criteria=self.fixture()
        chosen,warnings=select_documents([primary,criteria],[dict(anchor='IRP01',evidence_quote=primary['text'])])
        self.assertEqual(chosen[1]['selected_pages'],list(range(1,11))+[29,30])
        self.assertTrue(warnings)

    def test_no_reference_never_sends_full_criteria(self):
        from scoring_scope import select_documents
        primary,criteria=self.fixture()
        chosen,warnings=select_documents([primary,criteria],[])
        self.assertEqual(chosen,[primary])
        self.assertIn('NI poslan AI-ju',warnings[0])

    def test_unresolved_cross_reference_warns_without_full_document(self):
        from scoring_scope import select_documents
        primary,criteria=self.fixture();criteria['page_texts'][3]['text']='Glej poglavje 4.2'
        chosen,warnings=select_documents([primary,criteria],[dict(anchor='IRP01')])
        self.assertLess(len(chosen[1]['selected_pages']),30)
        self.assertTrue(any('nerešeni sklici' in w for w in warnings))

    def test_ai_reads_other_documents_for_reference_only(self):
        primary,criteria=self.fixture()
        response=Mock(ok=True,json=lambda:{'choices':[{'message':{'content':json.dumps({'references':[{'anchor':'IRP01','evidence_quote':primary['text']}]})}}]})
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch('analyzer.requests.post',return_value=response) as request:
            refs,warnings=analyzer.extract_merit_references([primary,criteria])
        self.assertEqual(len(refs),1)
        self.assertEqual(request.call_count,1)
        self.assertEqual(request.call_args.kwargs['json']['messages'][1]['content'],primary['text'])

    def test_invented_reference_does_not_select_pages(self):
        primary,criteria=self.fixture()
        response=Mock(ok=True,json=lambda:{'choices':[{'message':{'content':json.dumps({'references':[{'anchor':'IRP99','evidence_quote':'Use IRP99.'}]})}}]})
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch('analyzer.requests.post',return_value=response):
            refs,warnings=analyzer.extract_merit_references([primary,criteria])
        self.assertEqual(refs,[])
        self.assertTrue(warnings)

    def test_no_bookmarks_or_heading_means_no_full_book_fallback(self):
        from scoring_scope import select_documents
        primary,criteria=self.fixture()
        for page in criteria['page_texts']:page.pop('sections',None)
        chosen,warnings=select_documents([primary,criteria],[dict(anchor='IRP01')])
        self.assertEqual(chosen,[primary])
        self.assertIn('NEPOPOLNA ANALIZA',warnings[0])

    def test_pipeline_excludes_criteria_completely(self):
        primary,criteria=self.fixture()
        result=analyzer.ExtractionResults();result.append({'label':'Verified'})
        with patch('analyzer.collect',return_value=([primary,criteria],[],1)),patch('analyzer.extract_merit_references',return_value=([dict(anchor='IRP01')],[])),patch('analyzer.ai_extract',return_value=result) as extract:
            output=analyzer.analyze(primary['url'])
        sent=extract.call_args.args[0]
        self.assertEqual(sent,[primary])
        self.assertEqual(len(output['documents']),1)

class UploadedDocumentRegression(unittest.TestCase):
    def fixture(self):
        return json.loads((Path(__file__).parent/'fixtures'/'irp16_excerpts.json').read_text(encoding='utf-8'))

    def test_explicit_45_point_threshold_on_original_page_4(self):
        f=self.fixture()
        doc=dict(url=URL,title='Javni razpis',pages=41,text=f['call_page_4'],page_texts=[dict(number=4,text=f['call_page_4'])])
        result=analyzer.explicit_minimum_points([doc])
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['expected'],45)
        self.assertEqual(result[0]['page_number'],4)
        self.assertIn('30 %',result[0]['evidence_quote'])
        # A bare percentage is not an absolute points threshold.
        doc['page_texts'][0]['text']='Vstopni prag 30 % možnega števila točk.'
        self.assertEqual(analyzer.explicit_minimum_points([doc]),[])

    def test_separate_number_and_irp_title_lines(self):
        from scoring_scope import annotate_pages,select_documents
        f=self.fixture();pages=[dict(number=i,text='Continuation') for i in range(1,99)]
        pages[78]['text']=f['criteria_page_79'];pages[89]['text']=f['criteria_next_heading']
        annotate_pages(pages,[])
        doc=dict(title='Merila',url=URL,pages=98,page_texts=pages,text='all')
        selected,warnings=select_documents([doc],[dict(anchor='Naložbe v prilagoditev na podnebne spremembe pri trajnih nasadih')])
        self.assertEqual(selected[0]['selected_pages'],list(range(79,91)))

    def test_version_8_reference_does_not_accept_version_11_cover(self):
        from scoring_scope import select_documents
        f=self.fixture()
        primary=dict(title='Razpis',text=f['call_page_4'])
        criteria=dict(title='Merila',url=URL,text=f['criteria_cover'],page_texts=[dict(number=1,text=f['criteria_cover'])])
        selected,warnings=select_documents([primary,criteria],[dict(anchor='IRP16')])
        self.assertEqual(selected,[primary])
        self.assertTrue(any('8.' in w and '11.' in w and 'NI poslan' in w for w in warnings))

class LegalExplanation(unittest.TestCase):
    def response(self,provision):
        return Mock(ok=True,json=lambda:{'output':[
            {'type':'web_search_call','action':{'sources':[{'url':provision['source_url']}]}},
            {'type':'message','content':[{'type':'output_text','text':json.dumps({'provisions':[provision]})}]}]})

    def provision(self):
        return dict(law_title='Uredba – testni primer',provision='20. člen, prvi odstavek',source_url='https://pisrs.si/pregledPredpisa?id=TEST',source_quote='Vlagatelj mora biti vpisan v register kmetijskih gospodarstev.',explanation='Kmetija mora biti vpisana v register kmetijskih gospodarstev.',version_note='Časovno veljavnost je treba potrditi.')

    def test_grounded_quote_is_verified_before_explanation(self):
        import legal_explainer as legal
        p=self.provision()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch('legal_explainer.requests.post',return_value=self.response(p)),patch('legal_explainer.source_text',return_value=p['source_quote']):
            result=legal.explain({'evidence_quote':'Pogoji iz 20. člena uredbe.'},'Uredba – testni primer')
        self.assertEqual(result['status'],'explained')
        self.assertEqual(result['provisions'][0]['explanation'],p['explanation'])

    def test_invented_quote_is_not_explained(self):
        import legal_explainer as legal
        p=self.provision()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch('legal_explainer.requests.post',return_value=self.response(p)),patch('legal_explainer.source_text',return_value='Something else'):
            result=legal.explain({'evidence_quote':'Pogoji iz 20. člena uredbe.'},'Uredba')
        self.assertEqual(result['status'],'unresolved')
        self.assertEqual(result['provisions'],[])

    def test_unofficial_source_rejected(self):
        import legal_explainer as legal
        p=self.provision();p['source_url']='https://example.com/law'
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch('legal_explainer.requests.post',return_value=self.response(p)),patch('legal_explainer.source_text') as fetch:
            result=legal.explain({'evidence_quote':'20. člen'},'Uredba')
        fetch.assert_not_called();self.assertEqual(result['status'],'unresolved')

    def test_references_remain_manual_and_duplicate_lookup_is_reused(self):
        import legal_explainer as legal
        rule=dict(fact_key='cows_min',operator='gte',expected=20,fixed=True,evidence_quote='Izpolnjuje 20. člen uredbe, razen tretjega odstavka.')
        with patch('legal_explainer.explain',return_value={'status':'unresolved','message':'No source','provisions':[]}) as explain:
            result=legal.enrich([rule.copy(),rule.copy()],[dict(text='Uredba')])
        self.assertEqual(explain.call_count,1)
        self.assertEqual(result[0]['fact_key'],'unknown')
        self.assertIn('razen tretjega',result[0]['evidence_quote'])

    def test_criteria_not_downloaded(self):
        html=b'<main><a href="https://www.gov.si/assets/Merila_za_izbor.pdf">Merila za izbor</a><a href="https://www.gov.si/assets/Razpis.pdf">Javni razpis</a></main>'
        with fitz.open() as doc:
            doc.new_page().insert_text((40,60),'Official call document with sufficient text.');pdf=doc.tobytes()
        with patch('analyzer.get',side_effect=[('https://www.gov.si/call',html,'text/html'),('https://www.gov.si/assets/Razpis.pdf',pdf,'application/pdf')]) as fetch:
            docs,errors,count=analyzer.collect('https://www.gov.si/call')
        self.assertEqual(fetch.call_count,2)
        self.assertEqual(count,1)
        self.assertFalse(any('Merila' in d['url'] for d in docs))

    def test_legal_resolution_persists_without_destroying_other_data(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'DB',Path(tmp)/'legal.sqlite3'):
            app.init()
            with app.conn() as c:tid=c.execute("insert into tenders(title,url) values('Test',?)",(URL,)).lastrowid
            item=dict(label='Register',fact_key='unknown',operator='none',expected=None,mandatory=True,fixed=False,evidence_url=URL,evidence_quote='20. člen',explanation='See law',legal_resolution={'status':'explained','message':'Review','provisions':[self.provision()]})
            result=dict(conditions=[item],digest='hash',mode='AI',documents=[],warnings=[],pdf_links_found=1)
            with patch('app.analyze',return_value=result):app.analyze_tender(tid)
            stored=app.automated_assessment(tid,app.DEFAULT)['conditions'][0]
            self.assertEqual(json.loads(stored['legal_resolution'])['provisions'][0]['provision'],'20. člen, prvi odstavek')
            app.init()
            with app.conn() as c:self.assertEqual(c.execute('select count(*) from analysis_conditions').fetchone()[0],1)
