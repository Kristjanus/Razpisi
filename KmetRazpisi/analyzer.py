"""SKP document retrieval and cautious AI condition extraction.
Requires requests and bs4; optional pymupdf for PDF and OPENAI_API_KEY for AI.
"""
import io, json, os, re, hashlib
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

HEADERS={'User-Agent':'KmetRazpisi/1.2 (private SKP document review)'}
MAX_DOCS=8
MAX_BYTES=12_000_000

def allowed(url):
    p=urlparse(url)
    return p.scheme=='https' and (p.hostname=='gov.si' or p.hostname=='www.gov.si' or (p.hostname or '').endswith('.gov.si')) and not p.username and not p.password

def get(url):
    if not allowed(url): raise ValueError('Dovoljene so samo uradne HTTPS povezave gov.si')
    r=requests.get(url,timeout=35,headers=HEADERS,allow_redirects=True,stream=True)
    r.raise_for_status()
    if not allowed(r.url): raise ValueError('Preusmeritev izven gov.si')
    raw=bytearray()
    for chunk in r.iter_content(65536):
        raw.extend(chunk)
        if len(raw)>MAX_BYTES:raise ValueError('Dokument je prevelik (več kot 12 MB)')
    return r.url,bytes(raw),r.headers.get('content-type','')

def extract_html(data):
    soup=BeautifulSoup(data,'html.parser')
    for el in soup(['script','style','nav','footer','header']):el.decompose()
    main=soup.select_one('main') or soup.select_one('article') or soup
    text='\n'.join(s.strip() for s in main.get_text('\n').splitlines() if s.strip())
    return text[:110000]

def collect(url):
    final,raw,ctype=get(url)
    if b'%PDF-' in raw[:10]:
        raise ValueError('Glavna povezava naj bo spletna objava razpisa, ne PDF')
    soup=BeautifulSoup(raw,'html.parser')
    text=extract_html(raw)
    docs=[{'url':final,'title':'Uradna spletna objava','text':text,'pages':None}]
    seen={final}
    candidates=[]
    for a in soup.select('a[href]'):
        href=urljoin(final,a['href']).split('#')[0]
        label=' '.join(a.get_text(' ',strip=True).split())[:150]
        if href in seen or not allowed(href):continue
        if re.search(r'\.pdf(?:\?|$)',href,re.I) or ('pdf' in label.lower() and 'download' in href.lower()):
            seen.add(href);candidates.append((href,label))
    failures=[]
    for href,label in candidates[:MAX_DOCS]:
        try:
            dest,pdf,ct=get(href)
            if not pdf.startswith(b'%PDF-'):continue
            try: import fitz
            except ImportError:
                failures.append('Za PDF priloge namesti knjižnico pymupdf: python -m pip install pymupdf')
                break
            document=fitz.open(stream=pdf,filetype='pdf')
            if len(document)>150:failures.append('PDF ima več kot 150 strani; prebranih prvih 150')
            chunks=[]
            for i in range(min(len(document),150)):
                page_text=document[i].get_text('text').strip()
                if page_text:chunks.append(f'[STRAN {i+1}]\n{page_text}')
            docs.append({'url':dest,'title':label or 'PDF priloga','text':'\n'.join(chunks)[:160000],'pages':len(document)})
        except Exception as ex:failures.append(f'{label or href}: {str(ex)[:140]}')
    return docs,failures,len(candidates)

# Safe conservative rule-based fallback. All these remain UNVERIFIED.
KEYWORDS=[('Gorsko območje OMD',r'gorsk(?:em|o|ih|a|ega)\s+območj|območj.{0,15}gorsk','mountain_area',True),
          ('Vpis v register kmetijskih gospodarstev',r'vpisan.{0,40}(?:register kmetijskih gospodarstev|RKG)|register kmetijskih gospodarstev','farm_registered',True),
          ('Ekološka pridelava',r'ekološk(?:a|o|e|i|em)\s+(?:pridelav|kmetij|rej)','organic',True),
          ('Paša živali',r'(?:obvezn.{0,25}paš|paš.{0,35}goved)','pasture',True)]

def fallback(docs):
    result=[]
    for doc in docs:
        txt=doc['text']
        for label,pattern,key,expected in KEYWORDS:
            m=re.search(pattern,txt,re.I)
            if not m:continue
            excerpt=txt[max(0,m.start()-170):min(len(txt),m.end()+240)].replace('\n',' ')
            result.append({'label':'Preveri: '+label,'fact_key':key,'operator':'eq','expected':expected,
                'mandatory':False,'fixed':False,'evidence_url':doc['url'],'evidence_quote':excerpt[:380],
                'explanation':'Ključna beseda je zaznana, vendar to NI potrjen pogoj razpisa.'})
    return result[:24]

def ai_extract(docs):
    key=os.getenv('OPENAI_API_KEY','').strip()
    if not key:return None
    context='\n\n'.join(f'VIR: {d["url"]}\nNASLOV: {d["title"]}\n{d["text"][:44000]}' for d in docs)[:105000]
    schema={'type':'object','additionalProperties':False,'properties':{'conditions':{'type':'array','items':{'type':'object','additionalProperties':False,'properties':{
        'label':{'type':'string'},'fact_key':{'type':'string','enum':['municipality','activity','mountain_area','cows_min','cows_max','land_min','land_max','milk_min','milk_max','pasture','farm_registered','legal_form','omd_points','organic','unknown']},
        'operator':{'type':'string','enum':['eq','neq','gte','lte','in','contains','none']},'expected':{'type':['string','number','boolean','null']},
        'mandatory':{'type':'boolean'},'fixed':{'type':'boolean'},'evidence_url':{'type':'string'},'evidence_quote':{'type':'string'},'explanation':{'type':'string'}},
        'required':['label','fact_key','operator','expected','mandatory','fixed','evidence_url','evidence_quote','explanation']}}},'required':['conditions']}
    prompt=('Izlušči SAMO izrecne pogoje upravičenosti za prijavitelja ali kmetijo iz slovenskega razpisa SKP. '
      'Ne izmišljaj si pogojev, zneskov ali datumov. Vsak pogoj mora imeti dobeseden kratek citat iz dokumenta '
      'in točen URL vira. Če pogoja ni mogoče enostavno in zanesljivo izraziti z enim od znanih fact_key, '
      'uporabi fact_key="unknown", operator="none", expected=null. Če je pogoj izbiren, mandatory=false. '
      'fixed=true samo, če iz besedila jasno izhaja, da ga ni mogoče urediti pred relevantnim presečnim datumom. '
      'Pogoji bodo vedno najprej nepreverjeni; tvoje ocene ne pomenijo pravne presoje. '
      'Če ni dokazov, vrni prazen seznam. Največ 35 pogojev.')
    payload={'model':os.getenv('OPENAI_MODEL','gpt-4.1-mini'),'messages':[{'role':'system','content':prompt},
      {'role':'user','content':context}], 'response_format':{'type':'json_schema','json_schema':{'name':'skp_conditions','strict':True,'schema':schema}},'temperature':0}
    resp=requests.post('https://api.openai.com/v1/chat/completions',headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},json=payload,timeout=150)
    if not resp.ok:raise ValueError('AI storitev: '+str(resp.status_code)+' '+resp.text[:300])
    output=json.loads(resp.json()['choices'][0]['message']['content'])
    valid_urls={d['url'] for d in docs}
    results=[]
    for item in output['conditions'][:35]:
        if item['evidence_url'] not in valid_urls:continue
        if not item['evidence_quote'].strip():continue
        source=next(d for d in docs if d['url']==item['evidence_url'])
        # Loose whitespace normalization to tolerate PDF line wrapping; never invent evidence.
        norm=lambda x:re.sub(r'\s+',' ',x).strip().lower()
        if norm(item['evidence_quote']) not in norm(source['text']):continue
        results.append(item)
    return results

def analyze(url):
    docs,errors,found=collect(url)
    extracted=ai_extract(docs)
    mode='AI' if extracted is not None else 'ključne besede (brez AI)'
    conditions=extracted if extracted is not None else fallback(docs)
    digest=hashlib.sha256((''.join(d['url']+d['text'] for d in docs)).encode()).hexdigest()
    return {'conditions':conditions,'documents':[{'url':d['url'],'title':d['title'],'pages':d['pages'],'length':len(d['text'])} for d in docs],
            'warnings':errors,'pdf_links_found':found,'mode':mode,'digest':digest}
