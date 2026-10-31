import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import requests
import pymupdf
import analyzer
import app
import legal_explainer as legal
from condition_review import deduplicate
from tender_sources import prescribed_links,load_prescribed
from law_documents import parse_law

CALL='https://www.gov.si/call/'
PDF='https://www.gov.si/assets/Javni-razpis.pdf'
LAW='https://pisrs.si/api/datoteke/integracije/493126267'

def condition(label='Kmetija mora biti vpisana v register',quote='Kmetija mora biti vpisana v register.'):
    return dict(label=label,evidence_quote=quote,fact_key='unknown',operator='none',expected=None,mandatory=True,fixed=False,evidence_url=PDF,document_title='Javni razpis',page_number=1,explanation='Obvezna zahteva')

class DocumentOnly(unittest.TestCase):
    def test_predpisi_links_only_within_section(self):
        raw=f'<main><h2>Predpisi</h2><a href="{LAW}">Uredba</a><h2>Drugo</h2><a href="https://pisrs.si/other">Druga</a></main>'.encode()
        self.assertEqual(prescribed_links(raw,CALL),[dict(url=LAW,title='Uredba')])

    def test_website_budget_never_passes_to_extraction_model(self):
        html=f'<main><p>SECRET_WEBSITE_BUDGET_10000000</p><a href="{PDF}">Javni razpis</a><h2>Predpisi</h2><a href="{LAW}">Uredba</a></main>'.encode()
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((40,60),'The applicant must meet this formal eligibility condition.');raw=pdf.tobytes()
        extracted=analyzer.ExtractionResults();extracted.append(condition())
        with patch('analyzer.get',side_effect=[(CALL,html,'text/html'),(PDF,raw,'application/pdf')]),patch('analyzer.load_prescribed',return_value=([],['PREDPIS NI DOSTOPEN: Uredba'])),patch('analyzer.ai_extract',return_value=extracted) as ai:
            result=analyzer.analyze(CALL)
        sent=ai.call_args.args[0]
        self.assertEqual(len(sent),1)
        self.assertEqual(sent[0]['title'],'Javni razpis')
        self.assertNotIn('SECRET_WEBSITE_BUDGET',json.dumps(sent))
        self.assertTrue(any('PREDPIS NI DOSTOPEN' in w for w in result['warnings']))

    def test_unavailable_law_names_link_and_reason(self):
        error=requests.HTTPError(response=Mock(status_code=403))
        with patch('tender_sources.source_text',side_effect=error),patch('tender_sources.LawLibrary.entries',return_value=[]):
            docs,warnings=load_prescribed([dict(url=LAW,title='Uredba o skupnih določbah')])
        self.assertEqual(docs,[])
        self.assertIn('Uredba o skupnih določbah',warnings[0]);self.assertIn(LAW,warnings[0]);self.assertIn('HTTP 403',warnings[0])

    def test_duplicate_keeps_additional_evidence_and_different_years_stay_separate(self):
        one=condition();two={**one,'label':'  KMETIJA mora biti vpisana v register. ','evidence_url':'https://www.gov.si/annex.pdf','page_number':2}
        result=deduplicate([one,two])
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['additional_sources'][0]['page_number'],2)
        a=condition(quote='Vpis mora veljati v letu 2025.');b=condition(quote='Vpis mora veljati v letu 2026.')
        self.assertEqual(len(deduplicate([a,b])),2)

    def test_each_article_becomes_separate_condition(self):
        law=parse_law('27. člen\n(1) Vlagatelj mora biti vpisan v register kmetijskih gospodarstev.\n28. člen\n(1) Vlagatelj mora predložiti načrt naložbe z dokazili.\n29. člen\n(1) Vlagatelj mora imeti urejeno pravico uporabe zemljišča.')
        parent=condition(label='Pogoji iz 27., 28. in 29. člena uredbe',quote='Izpolnjevati mora 27., 28. in 29. člen uredbe, razen tretje točke 27. člena.')
        plan=Mock(ok=True,json=lambda:{'choices':[{'message':{'content':json.dumps({'references':[{'source_url':LAW,'provision':'27., 28. in 29. člen, razen tretje točke 27. člena'}]})}}]})
        observed=[]
        def expand_one(c,ref,text,warnings):
            observed.append((c['evidence_quote'],ref['provision'],text))
            return [{**ref,'explanation':'Zahteva '+ref['provision'],'source_quote':text.split('\n',1)[1],'version_note':'Review'}]
        docs=[dict(title='Razpis',url=PDF,text=parent['evidence_quote']),dict(kind='law',title='Uredba',url=LAW,text='law',law=law),dict(kind='legal_catalog',metadata_only=True,url=CALL,text='')]
        with patch('legal_explainer.requests.post',return_value=plan),patch('legal_explainer.explain_selected',side_effect=expand_one):
            result=legal.enrich([parent],docs)
        self.assertEqual(len(result),3)
        self.assertEqual([c['label'] for c in result],['Zahteva 27. člen','Zahteva 28. člen','Zahteva 29. člen'])
        self.assertTrue(all('razen tretje točke' in quote for quote,ref,text in observed))
        self.assertTrue(all(len(c['legal_resolution']['provisions'])==1 for c in result))

    def test_several_atomic_requirements_from_one_article_are_preserved(self):
        text='27. člen\nPrva obveznost: vlagatelj mora biti vpisan v register.\nDruga obveznost: vlagatelj mora imeti poravnane obveznosti.'
        requirements=[dict(explanation='Vpis v register',source_quote='Prva obveznost: vlagatelj mora biti vpisan v register.',version_note='Review'),dict(explanation='Poravnane obveznosti',source_quote='Druga obveznost: vlagatelj mora imeti poravnane obveznosti.',version_note='Review')]
        response=Mock(ok=True,json=lambda:{'choices':[{'message':{'content':json.dumps({'conditions':requirements})}}]})
        with patch('legal_explainer.requests.post',return_value=response):
            result=legal.explain_selected(condition(),dict(source_url=LAW,law_title='Uredba',provision='27. člen'),text,[])
        self.assertEqual(len(result),2)

    def test_missing_supplied_law_cannot_be_presented_as_resolved(self):
        parent=condition(label='27. člen uredbe',quote='Izpolnjevati mora 27. člen uredbe.')
        with patch('legal_explainer.requests.post') as ai:
            result=legal.enrich([parent],[dict(kind='legal_catalog',metadata_only=True,text='',url=CALL,title='Predpisi')])
        ai.assert_not_called()
        self.assertEqual(result[0]['legal_resolution']['status'],'unresolved')
        self.assertIn('ni preverjena',result[0]['label'])

    def test_additional_sources_survive_database_save(self):
        item=condition();item['additional_sources']=[dict(evidence_url=PDF,evidence_quote='Drugi citat',document_title='Priloga',page_number=2)]
        response=dict(conditions=[item],digest='hash',mode='AI',documents=[],warnings=[],pdf_links_found=1)
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'DB',Path(tmp)/'db.sqlite3'):
            app.init()
            with app.conn() as db:tid=db.execute("INSERT INTO tenders(title,url) VALUES('Test',?)",(CALL,)).lastrowid
            with patch('app.analyze',return_value=response):app.analyze_tender(tid)
            stored=app.automated_assessment(tid,app.DEFAULT)['conditions'][0]
            self.assertEqual(json.loads(stored['additional_sources'])[0]['document_title'],'Priloga')

class LegalCoverage(unittest.TestCase):
    def test_model_cannot_silently_drop_two_articles(self):
        law=parse_law('27. člen\nVlagatelj mora biti vpisan v register kmetijskih gospodarstev.\n28. člen\nPredložiti mora poslovni načrt naložbe.\n29. člen\nPredložiti mora dokazilo o lastništvu.')
        c=condition(label='27., 28. in 29. člen',quote='Izpolnjevanje 27., 28. in 29. člena uredbe.')
        reply=Mock(ok=True,json=lambda:{'choices':[{'message':{'content':json.dumps({'references':[{'source_url':LAW,'provision':'27. člen'}]})}}]})
        with patch('legal_explainer.requests.post',return_value=reply),patch('legal_explainer.explain_selected') as explain:
            result=legal.resolve_supplied(c,[dict(url=LAW,title='Uredba',law=law)],'Kontekst')
        self.assertEqual(result['status'],'unresolved')
        explain.assert_not_called()

class DuplicateCallFormats(unittest.TestCase):
    def test_pdf_preferred_over_docx_for_same_call_without_skipping_amendment(self):
        amendment='https://www.gov.si/assets/Sprememba.pdf'
        html=f'<main><a href="{PDF}">Javni razpis</a><a href="{PDF[:-4]}.docx">Javni razpis</a><a href="{amendment}">Sprememba javnega razpisa</a></main>'.encode()
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((40,60),'The applicant must meet the formal conditions stated here.');raw=pdf.tobytes()
        with patch('analyzer.get',side_effect=[(CALL,html,'text/html'),(PDF,raw,'application/pdf'),(amendment,raw,'application/pdf')]) as fetch:
            docs,errors,count=analyzer.collect(CALL)
        self.assertEqual(errors,[]);self.assertEqual(count,2)
        self.assertFalse(any(d['url'].endswith('.docx') for d in docs))
        self.assertEqual(fetch.call_count,3)

    def test_explanation_section_numbers_do_not_create_false_distinctions(self):
        one=condition(label='Poslovni načrt mora biti izdelan najmanj do 31. 12. 2034',quote='poslovni načrt mora biti v skladu s prvim odstavkom 29. člena uredbe izdelan najmanj do 31. 12. 2034')
        two={**one,'explanation':'Izrecna obveznost v 5.1.2.c','evidence_url':'https://www.gov.si/another.pdf'}
        one['explanation']='Izrecno zahtevan rok poslovnega načrta.'
        self.assertEqual(len(deduplicate([one,two])),1)

    def test_obvious_title_variants_with_same_scope_are_merged(self):
        one=condition(label='Vlagatelj mora imeti v letu 2025 prihodek najmanj 1,5 minimalne plače',quote='V letu 2025 ima prihodek najmanj 1,5 minimalne plače.')
        two={**one,'label':'Vlagatelj ima v letu 2025 prihodek najmanj 1,5 minimalne plače'}
        self.assertEqual(len(deduplicate([one,two])),1)

class ScoringNotEligibility(unittest.TestCase):
    def test_optional_scoring_criterion_is_not_a_mandatory_condition(self):
        quote='Vlagatelj mora biti član skupine proizvajalcev ali zadruge.'
        doc=dict(url=PDF,title='Javni razpis',text=quote,pages=1,page_texts=[dict(number=8,text=quote)])
        item={**condition(label='Članstvo za dodatne točke',quote=quote),'category':'scoring'}
        response=Mock(ok=True,json=lambda:{'choices':[{'message':{'content':json.dumps({'conditions':[item]})}}]})
        with patch.dict(__import__('os').environ,{'OPENAI_API_KEY':'test'}),patch('analyzer.requests.post',return_value=response):
            self.assertEqual(analyzer.ai_extract([doc]),[])
