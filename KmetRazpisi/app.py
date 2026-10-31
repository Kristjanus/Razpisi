import os,sqlite3,json,datetime,threading,hashlib,urllib.parse,smtplib
from email.message import EmailMessage
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from html import escape
import requests
from bs4 import BeautifulSoup
from analyzer import analyze
from eligibility import evaluate
from version import VERSION
from law_documents import LawLibrary
from legal_explainer import import_law_url
import analysis_jobs
from skp import SOURCE_URL, load_calls, listed_call

ROOT=Path(__file__).parent; DB=Path(os.getenv('KMETRAZPISI_DB', str(ROOT/'kmetrazpisi.sqlite3'))); PORT=int(os.getenv('PORT','8765'))
SOURCES=[('GOV.SI – SKP',SOURCE_URL)]
SKP_PREFIX='https://www.gov.si/zbirke/projekti-in-programi/skupna-kmetijska-politika/'
DEFAULT={'municipality':'Ivančna Gorica','activity':'mlečna reja','mountain_area':True,'cows_min':20,'cows_max':50,'land_min':30,'land_max':60,'milk_min':200000,'milk_max':300000,'pasture':False,'farm_registered':None,'legal_form':None,'holder_birthdate':None,'omd_points':None,'organic':None,'investment_interests':['mehanizacija','hlev','dobrobit živali','predelava mleka']}
SCHEMA='''CREATE TABLE IF NOT EXISTS farm(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL,updated_at TEXT);
CREATE TABLE IF NOT EXISTS tenders(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,url TEXT UNIQUE,source TEXT,status TEXT DEFAULT 'nepreverjeno',deadline TEXT,description TEXT,document_text TEXT,content_hash TEXT,first_seen TEXT,last_seen TEXT,reviewed INTEGER DEFAULT 0,hidden_manual INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS conditions(id INTEGER PRIMARY KEY AUTOINCREMENT,tender_id INTEGER NOT NULL REFERENCES tenders(id),label TEXT NOT NULL,fact_key TEXT NOT NULL,operator TEXT NOT NULL,expected TEXT,mandatory INTEGER DEFAULT 1,fixed INTEGER DEFAULT 0,verified INTEGER DEFAULT 0,evidence_url TEXT,evidence_quote TEXT);
CREATE TABLE IF NOT EXISTS monitoring_runs(id INTEGER PRIMARY KEY AUTOINCREMENT,started TEXT,finished TEXT,source TEXT,success INTEGER,message TEXT,new_count INTEGER DEFAULT 0,changed_count INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS changes(id INTEGER PRIMARY KEY AUTOINCREMENT,tender_id INTEGER,changed_at TEXT,old_hash TEXT,new_hash TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS analysis_conditions(id INTEGER PRIMARY KEY AUTOINCREMENT,tender_id INTEGER NOT NULL, label TEXT NOT NULL,fact_key TEXT,operator TEXT,expected TEXT,mandatory INTEGER,fixed INTEGER,evidence_url TEXT,evidence_quote TEXT,explanation TEXT,analysis_mode TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS analysis_runs(tender_id INTEGER PRIMARY KEY,document_hash TEXT,mode TEXT,analyzed_at TEXT,documents TEXT,warnings TEXT);'''
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
def conn():
 c=sqlite3.connect(DB,timeout=15);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
def init():
 with conn() as c:
  c.executescript(SCHEMA)
  columns={r['name'] for r in c.execute('PRAGMA table_info(analysis_conditions)')}
  for name, kind in [('document_title','TEXT'),('page_number','INTEGER'),('legal_resolution','TEXT')]:
   if name not in columns:c.execute(f'ALTER TABLE analysis_conditions ADD COLUMN {name} {kind}')
  if not c.execute('SELECT 1 FROM farm').fetchone():c.execute('INSERT INTO farm VALUES(1,?,?)',(json.dumps(DEFAULT,ensure_ascii=False),now()))
  for name,url in SOURCES:c.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)',('source:'+name,url))
def farm():
 with conn() as c:return json.loads(c.execute('SELECT data FROM farm WHERE id=1').fetchone()['data'])
def assess(tid,f):
 with conn() as c:rows=[dict(r) for r in c.execute('SELECT * FROM conditions WHERE tender_id=?',(tid,))]
 out=[]
 for r in rows:
  e=json.loads(r['expected']) if r['expected'] else None
  state=evaluate({**r,'expected':e},f)
  out.append({**r,'result':state})
 # Legacy rules lack explicit exclusions, exceptions and reference dates.
 # Until these are reviewed, retain tenders in the visible list.
 hide=False
 return {'conditions':out,'auto_hide':hide,'status':'izključen' if hide else ('za preveriti' if any(r['result']!='met' or not r['verified'] for r in out) or not out else 'pogoji izpolnjeni')}
def automated_assessment(tid,f):
 with conn() as c:
  rows=[dict(r) for r in c.execute('SELECT * FROM analysis_conditions WHERE tender_id=? ORDER BY id',(tid,))]
  run=c.execute('SELECT * FROM analysis_runs WHERE tender_id=?',(tid,)).fetchone()
 out=[]
 for r in rows:
  expected=json.loads(r['expected']) if r['expected'] is not None else None
  state=evaluate({**r,'expected':expected},f)
  out.append({**r,'result':state,'verified':False})
 return {'conditions':out,'run':dict(run) if run else None,'auto_hide':False}

def analyze_tender(tid, progress=None):
 with conn() as c: r=c.execute('SELECT url FROM tenders WHERE id=?',(tid,)).fetchone()
 if not r:raise ValueError('Razpis ne obstaja')
 result=analyze(r['url'], progress=progress)
 with conn() as c:
  c.execute('DELETE FROM analysis_conditions WHERE tender_id=?',(tid,))
  for item in result['conditions']:
   c.execute('INSERT INTO analysis_conditions(tender_id,label,fact_key,operator,expected,mandatory,fixed,evidence_url,evidence_quote,explanation,analysis_mode,created_at,document_title,page_number,legal_resolution) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
    (tid,item['label'],item['fact_key'],item['operator'],json.dumps(item['expected'],ensure_ascii=False),int(item['mandatory']),int(item['fixed']),item['evidence_url'],item['evidence_quote'][:1500],item['explanation'][:900],result['mode'],now(),item.get('document_title'),item.get('page_number'),json.dumps(item.get('legal_resolution'),ensure_ascii=False)))
  c.execute('INSERT INTO analysis_runs(tender_id,document_hash,mode,analyzed_at,documents,warnings) VALUES(?,?,?,?,?,?) ON CONFLICT(tender_id) DO UPDATE SET document_hash=excluded.document_hash,mode=excluded.mode,analyzed_at=excluded.analyzed_at,documents=excluded.documents,warnings=excluded.warnings',
    (tid,result['digest'],result['mode'],now(),json.dumps(result['documents'],ensure_ascii=False),json.dumps(result['warnings'],ensure_ascii=False)))
 return {'count':len(result['conditions']),'documents':result['documents'],'warnings':result['warnings'],'mode':result['mode'],'pdf_links_found':result['pdf_links_found']}

def notify(subject,body):
 host=os.getenv('SMTP_HOST');recipient=os.getenv('ALERT_TO')
 if not host or not recipient:return
 msg=EmailMessage();msg['Subject']=subject;msg['From']=os.getenv('SMTP_FROM',os.getenv('SMTP_USER','kmetrazpisi@localhost'));msg['To']=recipient;msg.set_content(body)
 with smtplib.SMTP(host,int(os.getenv('SMTP_PORT','587')),timeout=15) as s:
  s.starttls();s.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD']);s.send_message(msg)
def scan():
 # Link discovery is intentionally conservative: ambiguous items stay unverified.
 summary=[];alerts=[]
 for name,url in SOURCES:
  start=now();added=changed=0
  try:
   links=load_calls()
   with conn() as c:
    for href,label in links.items():
     old=c.execute('SELECT id,title FROM tenders WHERE url=?',(href,)).fetchone()
     if old:
      c.execute('UPDATE tenders SET last_seen=? WHERE id=?',(now(),old['id']))
     else:
      c.execute('INSERT INTO tenders(title,url,source,status,first_seen,last_seen) VALUES(?,?,?,?,?,?)',(label,href,name,'nepreverjeno',now(),now()));added+=1;alerts.append(f'{label}\n{href}')
    c.execute('INSERT INTO monitoring_runs(started,finished,source,success,message,new_count,changed_count) VALUES(?,?,?,?,?,?,?)',(start,now(),name,1,f'Najdenih {len(links)} možnih povezav',added,changed))
   summary.append({'source':name,'new':added,'links':len(links),'ok':True})
  except Exception as ex:
   with conn() as c:c.execute('INSERT INTO monitoring_runs(started,finished,source,success,message) VALUES(?,?,?,?,?)',(start,now(),name,0,str(ex)[:300]))
   summary.append({'source':name,'ok':False,'error':str(ex)[:180]})
 if alerts:
  try:notify('KmetRazpisi: nove možne objave', '\n\n'.join(alerts[:30])+'\n\nObjave so nepreverjene; preverite uradno dokumentacijo.')
  except Exception as ex:summary.append({'email_error':str(ex)})
 return summary

def fetch_tender(tid):
 with conn() as c:r=c.execute('SELECT * FROM tenders WHERE id=?',(tid,)).fetchone()
 if not r:raise ValueError('Razpis ne obstaja')
 resp=requests.get(r['url'],timeout=30,headers={'User-Agent':'KmetRazpisi/1.0'});resp.raise_for_status()
 soup=BeautifulSoup(resp.text,'html.parser')
 for el in soup(['script','style','nav','footer','header']):el.decompose()
 main=soup.select_one('main') or soup.select_one('article') or soup
 text='\n'.join(line.strip() for line in main.get_text('\n').splitlines() if line.strip())[:100000]
 digest=hashlib.sha256(text.encode()).hexdigest()
 with conn() as c:
  if r['content_hash'] and r['content_hash']!=digest:
   c.execute('INSERT INTO changes(tender_id,changed_at,old_hash,new_hash) VALUES(?,?,?,?)',(tid,now(),r['content_hash'],digest))
   c.execute('UPDATE tenders SET reviewed=0 WHERE id=?',(tid,))
  c.execute('UPDATE tenders SET document_text=?,content_hash=?,last_seen=? WHERE id=?',(text,digest,now(),tid))
 return {'length':len(text),'changed':bool(r['content_hash'] and r['content_hash']!=digest)}

HTML=ROOT/'static'/'index.html'
class Handler(BaseHTTPRequestHandler):
 def _send(self,obj,status=200):
  raw=json.dumps(obj,ensure_ascii=False,default=str).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
 def _body(self):
  size=int(self.headers.get('Content-Length','0'))
  if size>1000000:raise ValueError('Prevelika zahteva')
  return json.loads(self.rfile.read(size) or '{}')
 def do_GET(self):
  p=urlparse(self.path).path
  if p=='/':
   raw=HTML.read_text(encoding='utf-8').replace('{{APP_VERSION}}', VERSION).encode('utf-8');self.send_response(200);self.send_header('Cache-Control','no-store');self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
  if p=='/api/laws':return self._send({'entries':LawLibrary().entries()})
  if p=='/api/state':
   f=farm()
   with conn() as c:
    ts=[dict(r) for r in c.execute("SELECT id,title,url,source,status,deadline,description,first_seen,last_seen,reviewed,hidden_manual FROM tenders WHERE source IN ('GOV.SI – SKP','Ročno dodano') AND url LIKE 'https://www.gov.si/zbirke/javne-objave/%' ORDER BY first_seen DESC LIMIT 1000")]
    runs=[dict(r) for r in c.execute('SELECT * FROM monitoring_runs ORDER BY id DESC LIMIT 12')]
    changes=[dict(r) for r in c.execute('SELECT * FROM changes ORDER BY id DESC LIMIT 30')]
   for t in ts:t['assessment']=assess(t['id'],f)
   self._send({'version':VERSION,'ai_configured':bool(os.getenv('OPENAI_API_KEY','').strip()),'farm':f,'tenders':ts,'runs':runs,'changes':changes,'sources':SOURCES});return
  if p.startswith('/api/tender/') and p.endswith('/analysis-progress'):
   try:tid=int(p.split('/')[3])
   except (ValueError,IndexError):return self._send({'error':'ID'},400)
   return self._send(analysis_jobs.status(tid))
  if p.startswith('/api/tender/'):
   try:tid=int(p.split('/')[-1])
   except: return self._send({'error':'ID'},400)
   with conn() as c:r=c.execute('SELECT * FROM tenders WHERE id=?',(tid,)).fetchone()
   return self._send({'tender':dict(r),'assessment':assess(tid,farm()),'automatic':automated_assessment(tid,farm())} if r else {'error':'Ni najdeno'},200 if r else 404)
  self._send({'error':'Ni najdeno'},404)
 def do_POST(self):
  try:
   p=urlparse(self.path).path;b=self._body()
   if p=='/api/laws/import':return self._send(import_law_url(b.get('url','').strip(),refresh=b.get('refresh') is True))
   if p=='/api/farm':
    if not isinstance(b,dict):raise ValueError('Neveljaven profil')
    with conn() as c:c.execute('UPDATE farm SET data=?,updated_at=? WHERE id=1',(json.dumps(b,ensure_ascii=False),now()))
    return self._send({'ok':True})
   if p=='/api/scan':return self._send({'results':scan()})
   if p=='/api/tenders':
    url=b.get('url','').strip()
    if not listed_call(url):raise ValueError('Povezava mora voditi na konkreten razpis v uradnem seznamu SKP; informativnih strani ni mogoče dodati kot razpis')
    with conn() as c:
     c.execute('INSERT OR IGNORE INTO tenders(title,url,source,status,first_seen,last_seen) VALUES(?,?,?,?,?,?)',(b.get('title') or url,url,'Ročno dodano','nepreverjeno',now(),now()))
    return self._send({'ok':True})
   if p.startswith('/api/tender/'):
    parts=p.split('/');tid=int(parts[3]);action=parts[4] if len(parts)>4 else ''
    if action=='analyze-start':
     with conn() as c:exists=c.execute('SELECT 1 FROM tenders WHERE id=?',(tid,)).fetchone()
     if not exists:return self._send({'error':'Razpis ne obstaja'},404)
     return self._send(analysis_jobs.start(tid,analyze_tender),202)
    if action=='analyze':return self._send(analyze_tender(tid))
    if action=='fetch':return self._send(fetch_tender(tid))
    if action=='update':
     allowed={'title','status','deadline','description','reviewed','hidden_manual'}
     fields={k:v for k,v in b.items() if k in allowed}
     if not fields:raise ValueError('Ni polj')
     with conn() as c:c.execute('UPDATE tenders SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),tid))
     return self._send({'ok':True})
    if action=='conditions':
     if b.get('operator') not in ('eq','neq','gte','lte','in','contains'):raise ValueError('Neznan operator')
     with conn() as c:c.execute('INSERT INTO conditions(tender_id,label,fact_key,operator,expected,mandatory,fixed,verified,evidence_url,evidence_quote) VALUES(?,?,?,?,?,?,?,?,?,?)',(tid,b['label'],b['fact_key'],b['operator'],json.dumps(b.get('expected'),ensure_ascii=False),int(bool(b.get('mandatory',True))),int(bool(b.get('fixed',False))),int(bool(b.get('verified',False))),b.get('evidence_url',''),b.get('evidence_quote','')))
     return self._send({'ok':True})
    if action=='delete-condition':
     with conn() as c:c.execute('DELETE FROM conditions WHERE id=? AND tender_id=?',(int(b['id']),tid))
     return self._send({'ok':True})
   self._send({'error':'Ni najdeno'},404)
  except Exception as ex:self._send({'error':str(ex)},400)
 def log_message(self,*args):pass
if __name__=='__main__':
 init()
 import sys
 if len(sys.argv)>1 and sys.argv[1]=='scan':print(json.dumps(scan(),ensure_ascii=False,indent=2))
 else:
  print(f'KmetRazpisi v{VERSION}: http://127.0.0.1:{PORT}');ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
