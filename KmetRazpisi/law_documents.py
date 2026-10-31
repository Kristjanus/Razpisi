"""Deterministic law parsing, exact provision selection and versioned local storage."""
import argparse
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

class LawParseError(ValueError):
    pass


def document_metadata(raw):
    if raw.startswith((b'%PDF-',b'PK',b'\xd0\xcf\x11\xe0')):return {}
    soup=BeautifulSoup(raw,'html.parser')
    name=soup.title.get_text(' ',strip=True) if soup.title else ''
    identifier=re.search(r'\b(?:URED|ZAKO|PRAV)\d+\b',name)
    version=soup.select_one('p.npb')
    date=soup.select_one('p.navezava-npb')
    date_match=re.search(r'(\d{2})[.](\d{2})[.](\d{4})',date.get_text(' ',strip=True)) if date else None
    return {'source_id':identifier[0] if identifier else None,
            'export_title':name,
            'law_title':' '.join(p.get_text(' ',strip=True) for p in soup.select('p.naslov')),
            'version_label':version.get_text(' ',strip=True) if version else None,
            'application_start':f'{date_match[3]}-{date_match[2]}-{date_match[1]}' if date_match else None,
            'version_verified_for_tender':False,
            'annexes':[{'title':a.get_text(' ',strip=True),'url':a.get('href')} for a in soup.select('p.priloga a[href]')],
            'chapters':[p.get_text(' ',strip=True) for p in soup.select('p.poglavje')]}


def decode_document(raw, content_type=''):
    if len(raw)>8_000_000:raise LawParseError('Predpis presega 8 MB')
    if raw.startswith(b'%PDF-'):
        import pymupdf
        with pymupdf.open(stream=raw,filetype='pdf') as doc:
            if doc.needs_pass:raise LawParseError('Predpis PDF je zaščiten')
            texts=[p.get_text('text') for p in doc]
            if any(not t.strip() for t in texts):raise LawParseError('Predpis vsebuje skenirane ali prazne PDF-strani; potrebna je preverjena OCR-obdelava')
            return '\n'.join(texts),'pdf'
    if raw.startswith(b'PK'):
        try:
            archive=zipfile.ZipFile(io.BytesIO(raw))
            if sum(f.file_size for f in archive.infolist())>24_000_000:
                archive.close();raise LawParseError('Word dokument je po razširitvi prevelik')
            document_xml=archive.read('word/document.xml')
        except (zipfile.BadZipFile,KeyError) as ex:
            raise LawParseError('Word dokument ni veljaven DOCX') from ex
        with archive:
            if sum(f.file_size for f in archive.infolist())>24_000_000:raise LawParseError('Word dokument je po razširitvi prevelik')
            try:root=ET.fromstring(document_xml)
            except ET.ParseError as ex:raise LawParseError('Word dokument vsebuje neveljaven XML') from ex
            ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            return '\n'.join(''.join(t.text or '' for t in p.iter(ns+'t')) for p in root.iter(ns+'p')),'docx'
    if raw.startswith(b'\xd0\xcf\x11\xe0'):
        raise LawParseError('Stari format DOC ni podprt; uporabite uradni HTML, DOCX ali PDF')
    soup=BeautifulSoup(raw,'html.parser')
    for node in soup(['script','style','nav','footer','header']):node.decompose()
    # PISRS semantic classes separate headings and annex links from article text.
    for node in soup.select('p.clen'):
        heading=' '.join(node.get_text(' ',strip=True).split())
        node.clear();node.append(heading)
    for node in soup.select('p.priloga,p.poglavje'):node.decompose()
    # Preserve inline text within paragraphs, and line boundaries between blocks.
    for node in soup.find_all(['p','div','section','article','h1','h2','h3','h4','li','tr','br']):
        node.insert_before('\n');node.insert_after('\n')
    return soup.get_text(' ',strip=False),'html'


def article_number(value):
    value=unicodedata.normalize('NFKC',str(value)).casefold()
    match=re.fullmatch(r'\s*(\d+)\s*\.?\s*([a-zčšž]?)\s*\.?\s*',value)
    if not match:raise LawParseError('Neveljavna oznaka člena: '+value)
    return str(int(match[1]))+('.'+match[2] if match[2] else '')


def _points(text):
    marks=list(re.finditer(r'^\s*(\d+|[a-zčšž])[.)][ \t]+',text,re.M|re.I))
    if any(m[1].isdigit() for m in marks) and any(not m[1].isdigit() for m in marks):
        raise LawParseError('Večnivojska hierarhija točk zahteva pregled; izberite celoten odstavek')
    output={}
    for index,mark in enumerate(marks):
        key=mark[1].casefold()
        if key in output:raise LawParseError('Dvoumna hierarhija točk; izberite celoten odstavek')
        stop=marks[index+1].start() if index+1<len(marks) else len(text)
        output[key]=text[mark.end():stop].strip()
    return output


def parse_law(text):
    text=unicodedata.normalize('NFKC',text).replace('\r\n','\n').replace('\r','\n')
    # A heading may be split across two lines in PDF or HTML.
    text=re.sub(r'(?m)^\s*(\d+\s*\.?\s*[a-zčšž]?\s*\.?)\s*\n\s*(člen)\s*$',r'\1 \2',text,flags=re.I)
    pattern=re.compile(r'^[ \t]*(?:(\d+\s*\.?\s*[a-zčšž]?\s*\.?)\s+člen|člen\s+(\d+[a-z]?))[ \t]*$',re.M|re.I)
    markers=list(pattern.finditer(text))
    if not markers:raise LawParseError('Besedilo ne vsebuje zanesljivih naslovov členov; lahko gre za spletni ovoj, sken ali nepodprt zapis')
    articles={};order=[]
    for index,mark in enumerate(markers):
        number=article_number(mark[1] or mark[2])
        if number in articles:raise LawParseError('Podvojena oznaka '+number+'. člena; besedilo zahteva pregled')
        end=markers[index+1].start() if index+1<len(markers) else len(text)
        body=text[mark.end():end].strip()
        if not body:raise LawParseError('Prazen '+number+'. člen')
        title=''
        heading=re.match(r'^\(([^\d\n][^\n]*)\)[ \t]*\n',body)
        if heading:title=heading[1].strip();body=body[heading.end():].strip()
        paragraphs={};paragraph_marks=list(re.finditer(r'^\s*\((\d+)\)[ \t]*',body,re.M))
        for pi,pm in enumerate(paragraph_marks):
            key=pm[1]
            if key in paragraphs:raise LawParseError('Podvojen odstavek v '+number+'. členu')
            stop=paragraph_marks[pi+1].start() if pi+1<len(paragraph_marks) else len(body)
            value=body[pm.end():stop].strip()
            try:points=_points(value);point_error=None
            except LawParseError as ex:points={};point_error=str(ex)
            paragraphs[key]={'text':value,'points':points,'point_error':point_error}
        try:points=_points(body) if not paragraphs else {};point_error=None
        except LawParseError as ex:points={};point_error=str(ex)
        articles[number]={'number':number,'title':title,'text':body,'paragraphs':paragraphs,'points':points,'point_error':point_error}
        order.append(number)
    numeric=[int(n.split('.')[0]) for n in order]
    warnings=[]
    if numeric!=sorted(numeric):warnings.append('Členi niso v naraščajočem vrstnem redu; potreben je pregled.')
    if numeric and numeric[0]!=1:warnings.append('Besedilo se ne začne s 1. členom; lahko je delni izvoz.')
    if any(b>a+1 for a,b in zip(numeric,numeric[1:])):warnings.append('V zaporedju členov so vrzeli; preverite črtane člene in popolnost vira.')
    return {'articles':articles,'order':order,'warnings':warnings}


def select_provision(law,article,paragraph=None,point=None):
    number=article_number(article)
    if number not in law['articles']:raise LawParseError('Zahtevani '+number+'. člen ni pridobljen')
    item=law['articles'][number]
    if paragraph is not None:
        entry=item['paragraphs'].get(str(paragraph))
        if entry is None:raise LawParseError('Zahtevani odstavek ni pridobljen')
    else:entry=item
    if point is not None:
        if entry.get('point_error'):raise LawParseError(entry['point_error'])
        value=entry['points'].get(str(point).casefold())
        if value is None:raise LawParseError('Zahtevana točka ni pridobljena ali hierarhija ni določljiva')
        return value
    return entry['text']


def articles_for_reference(law,reference):
    # Multiple article numbers and numbered ranges: preserve the entire range.
    patterns=[r'((?:\d+[.]?\s*[a-zčšž]?\s*(?:,\s*|in\s+|do\s+)?)+)člen\w*',r'člen\s+(\d+[a-z]?)']
    numbers=[]
    for pattern in patterns:
        for match in re.finditer(pattern,reference,re.I):
            segment=match[1]
            ids=re.findall(r'\d+(?:\s*\.\s*[a-zčšž](?![a-zčšž]))?',segment,re.I)
            if re.search(r'\bdo\b',segment) and len(ids)==2 and all(re.fullmatch(r'\d+',n) for n in ids):
                ids=[str(n) for n in range(int(ids[0]),int(ids[1])+1)]
            numbers.extend(article_number(n) for n in ids)
    numbers=list(dict.fromkeys(numbers))
    if not numbers:raise LawParseError('Iz navedbe ni mogoče določiti številke člena')
    selected=[]
    for number in numbers:
        body=select_provision(law,number)
        selected.append(f'{number}. člen\n{body}')
    text='\n\n'.join(selected)
    if len(text)>60000:raise LawParseError('Izbrane določbe presegajo 60.000 znakov; potrebna je dodatna razdelitev')
    return text,numbers


class LawLibrary:
    def __init__(self,path=None):
        self.path=Path(path or os.getenv('KMETRAZPISI_LAW_DB',str(Path(__file__).parent/'kmetrazpisi-laws.sqlite3')))

    def store(self,source_url,raw,text,format,law,version_label='nepotrjena časovna različica',metadata=None):
        digest=hashlib.sha256(raw).hexdigest()
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS law_versions(source_url TEXT,sha256 TEXT,version_label TEXT,fetched_at TEXT,format TEXT,text TEXT,structure TEXT,PRIMARY KEY(source_url,sha256))')
            columns={r[1] for r in db.execute('PRAGMA table_info(law_versions)')}
            if 'metadata' not in columns:db.execute('ALTER TABLE law_versions ADD COLUMN metadata TEXT')
            db.execute('INSERT INTO law_versions(source_url,sha256,version_label,fetched_at,format,text,structure,metadata) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source_url,sha256) DO UPDATE SET metadata=excluded.metadata,structure=excluded.structure,text=excluded.text',
                       (source_url,digest,version_label,datetime.datetime.now(datetime.timezone.utc).isoformat(),format,text,json.dumps(law,ensure_ascii=False),json.dumps(metadata or {},ensure_ascii=False)))
        return digest


    def load(self,source_url,sha256):
        if not self.path.exists():raise LawParseError('Lokalna knjižnica še ne obstaja')
        with sqlite3.connect(self.path) as db:
            columns={r[1] for r in db.execute('PRAGMA table_info(law_versions)')}
            fields='version_label,text,structure'+(',metadata' if 'metadata' in columns else '')
            row=db.execute('SELECT '+fields+' FROM law_versions WHERE source_url=? AND sha256=?',(source_url,sha256)).fetchone()
        if row is None:raise LawParseError('Zahtevana različica ni v lokalni knjižnici')
        return {'version_label':row[0],'text':row[1],'law':json.loads(row[2]),'metadata':json.loads(row[3] or '{}') if len(row)>3 else {}}


    def entries(self):
        if not self.path.exists():return []
        with sqlite3.connect(self.path) as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'law_versions' not in tables:return []
            columns={r[1] for r in db.execute('PRAGMA table_info(law_versions)')}
            if 'metadata' not in columns:return []
            rows=db.execute('SELECT source_url,sha256,fetched_at,format,metadata FROM law_versions ORDER BY fetched_at DESC').fetchall()
        result=[]
        for url,digest,fetched,format,raw_metadata in rows:
            metadata=json.loads(raw_metadata or '{}')
            if not metadata.get('source_id'):continue
            result.append(dict(source_url=url,sha256=digest,fetched_at=fetched,format=format,**metadata))
        return result

    def find_url(self,url):
        entries=[e for e in self.entries() if e['source_url']==url and e.get('version_label')]
        if len(entries)!=1:return None
        return {**self.load(url,entries[0]['sha256']),**entries[0]}

    def remember_binding(self,key,references):
        pinned=[]
        for reference in references:
            cached=self.find_url(reference['source_url'])
            if cached is None:return
            pinned.append({k:reference[k] for k in ('law_title','provision','source_url')})
            pinned[-1]['sha256']=cached['sha256']
        if not pinned:return
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS legal_bindings(key TEXT PRIMARY KEY,references_json TEXT NOT NULL)')
            db.execute('INSERT INTO legal_bindings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET references_json=excluded.references_json',(key,json.dumps(pinned,ensure_ascii=False)))

    def binding(self,key):
        if not self.path.exists():return None
        with sqlite3.connect(self.path) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='legal_bindings'").fetchone():return None
            row=db.execute('SELECT references_json FROM legal_bindings WHERE key=?',(key,)).fetchone()
        if row is None:return None
        references=json.loads(row[0])
        for reference in references:
            try:self.load(reference['source_url'],reference['sha256'])
            except LawParseError:return None
        return references


def main():
    parser=argparse.ArgumentParser(description='Razdeli lokalni predpis in izberi določbo brez AI')
    parser.add_argument('file');parser.add_argument('--source-url',required=True);parser.add_argument('--version',required=True)
    parser.add_argument('--database');parser.add_argument('--article',required=True);parser.add_argument('--paragraph');parser.add_argument('--point')
    args=parser.parse_args()
    raw=Path(args.file).read_bytes();text,format=decode_document(raw);law=parse_law(text)
    selected=select_provision(law,args.article,args.paragraph,args.point)
    metadata=document_metadata(raw)
    digest=LawLibrary(args.database).store(args.source_url,raw,text,format,law,args.version,metadata=metadata)
    print(json.dumps({'source_url':args.source_url,'version':args.version,'sha256':digest,'metadata':metadata,'warnings':law['warnings'],'selected_text':selected},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
