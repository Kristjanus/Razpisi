import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import zipfile
import pymupdf
import law_documents as laws
import legal_explainer as legal

TEXT='''Testni predpis
1. člen
(predmet)
(1) Ta uredba določa pogoje podpore.
(2) Za razlago glej 12. člen uredbe.
12. člen
(upravičenci)
(1) Vlagatelj mora biti vpisan v register kmetijskih gospodarstev.
(2) Predložiti je treba:
a) dokazilo o lastništvu;
b) izjavo upravičenca.
12.a člen
(izjema)
(1) Izjema velja le za določene vlagatelje.
13. člen
Obveznosti upravičenca ostanejo v veljavi.
'''

class LawParser(unittest.TestCase):
    def test_articles_paragraphs_and_lettered_points(self):
        law=laws.parse_law(TEXT)
        self.assertEqual(law['order'],['1','12','12.a','13'])
        self.assertEqual(law['articles']['12']['title'],'upravičenci')
        self.assertIn('vpisan v register',laws.select_provision(law,12,1))
        self.assertEqual(laws.select_provision(law,12,2,'a'),'dokazilo o lastništvu;')
        self.assertIn('Izjema',laws.select_provision(law,'12.a',1))
        self.assertIn('vrzeli',' '.join(law['warnings']))

    def test_reference_inside_sentence_is_not_heading(self):
        law=laws.parse_law(TEXT)
        self.assertIn('glej 12. člen',laws.select_provision(law,1,2))
        self.assertEqual(len(law['articles']),4)

    def test_split_heading_and_european_style(self):
        law=laws.parse_law('12.\nčlen\nPrvi primer besedila.\nČlen 13\nDrugi primer besedila.')
        self.assertEqual(law['order'],['12','13'])

    def test_duplicate_articles_and_missing_target_fail(self):
        with self.assertRaises(laws.LawParseError):laws.parse_law('1. člen\nA\n1. člen\nB')
        with self.assertRaises(laws.LawParseError):laws.select_provision(laws.parse_law(TEXT),99)
        with self.assertRaises(laws.LawParseError):laws.select_provision(laws.parse_law(TEXT),12,9)

    def test_numbered_range_does_not_drop_middle_articles(self):
        law=laws.parse_law('1. člen\nPrvi.\n2. člen\nDrugi.\n3. člen\nTretji.')
        text,numbers=laws.articles_for_reference(law,'1. do 3. člena, razen drugega odstavka')
        self.assertEqual(numbers,['1','2','3'])
        self.assertIn('Drugi.',text)

    def test_html_inline_tags_and_blocks_preserve_structure(self):
        html=b'<html><script>fake</script><p><b>12.</b> <span>\xc4\x8dlen</span></p><p>(upravi\xc4\x8denci)</p><p>(1) Vlagatelj mora biti vpisan v register.</p><p>13. \xc4\x8dlen</p><p>Druga dolo\xc4\x8dba.</p></html>'
        text,kind=laws.decode_document(html)
        law=laws.parse_law(text)
        self.assertEqual(kind,'html');self.assertEqual(law['order'],['12','13'])
        self.assertIn('vpisan',laws.select_provision(law,12,1))
        self.assertNotIn('fake',text)

    def test_docx_text_matches_article_selection(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive:
            paragraphs=''.join('<w:p><w:r><w:t>'+line+'</w:t></w:r></w:p>' for line in TEXT.splitlines())
            archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+paragraphs+'</w:body></w:document>')
        text,kind=laws.decode_document(stream.getvalue())
        self.assertEqual(kind,'docx')
        self.assertIn('dokazilo',laws.select_provision(laws.parse_law(text),12,2,'a'))

    def test_pdf_article_numbers(self):
        with pymupdf.open() as document:
            page=document.new_page()
            page.insert_htmlbox(pymupdf.Rect(40,40,550,700),'<p>12. člen</p><p>(1) Vlagatelj mora biti vpisan v register.</p><p>13. člen</p><p>Druga določba.</p>')
            raw=document.tobytes()
        text,kind=laws.decode_document(raw)
        self.assertEqual(kind,'pdf')
        self.assertIn('vpisan',laws.select_provision(laws.parse_law(text),12,1))

    def test_spa_shell_is_not_treated_as_law(self):
        text,_=laws.decode_document(b'<html><div id="app"></div><script src="main.js"></script></html>')
        with self.assertRaises(laws.LawParseError):laws.parse_law(text)

    def test_library_preserves_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            library=laws.LawLibrary(Path(tmp)/'laws.sqlite3')
            law=laws.parse_law(TEXT)
            first=library.store('https://pisrs.si/test',b'first',TEXT,'html',law,'2025')
            second=library.store('https://pisrs.si/test',b'second',TEXT,'html',law,'2026')
            self.assertNotEqual(first,second)
            self.assertEqual(library.load('https://pisrs.si/test',first)['version_label'],'2025')
            self.assertEqual(library.load('https://pisrs.si/test',second)['version_label'],'2026')

    def test_only_requested_article_sent_to_explanation_model(self):
        quote='Vlagatelj mora biti vpisan v register kmetijskih gospodarstev.'
        response=Mock(ok=True,json=lambda:{'choices':[{'message':{'content':json.dumps(dict(explanation='Vpis v register je obvezen.',source_quote=quote,version_note='Preveriti časovno veljavnost.'))}}]})
        selected,numbers=laws.articles_for_reference(laws.parse_law(TEXT),'12. člen, prvi odstavek')
        with patch('legal_explainer.requests.post',return_value=response) as request:
            result=legal.explain_selected({'evidence_quote':'Izpolnjevanje 12. člena.'},{'law_title':'Test','provision':'12. člen','source_url':'https://pisrs.si/test'},selected,[])
        sent=json.loads(request.call_args.kwargs['json']['messages'][1]['content'])['selected_articles']
        self.assertNotIn('Obveznosti upravičenca',sent)
        self.assertNotIn('Izjema velja',sent)
        self.assertIsNotNone(result)

class AmbiguousLawStructure(unittest.TestCase):
    def test_mixed_nested_points_are_not_flattened_for_selection(self):
        law=laws.parse_law('1. člen\n(1) Pogoji:\n1. Prvi pogoj:\na) podpogoj A;\nb) podpogoj B.\n2. Drugi pogoj.')
        with self.assertRaises(laws.LawParseError):laws.select_provision(law,1,1,'a')
        self.assertIn('podpogoj A',laws.select_provision(law,1,1))

    def test_invalid_word_zip_has_specific_error(self):
        with self.assertRaises(laws.LawParseError):laws.decode_document(b'PKnot-a-valid-zip')
