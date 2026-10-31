"""The tender web page supplies links only; never pass its prose to AI."""
import re
from urllib.parse import urljoin,urlparse,parse_qs
from bs4 import BeautifulSoup
from legal_explainer import official,source_text
from law_documents import LawLibrary,parse_law


def prescribed_links(raw,base):
    soup=BeautifulSoup(raw,'html.parser');result=[];seen=set()
    for heading in soup.find_all(re.compile('^h[1-6]$')):
        if heading.get_text(' ',strip=True).strip(':').casefold()!='predpisi':continue
        level=int(heading.name[1])
        for node in heading.next_elements:
            if getattr(node,'name',None) and re.fullmatch('h[1-6]',node.name) and int(node.name[1])<=level:break
            if getattr(node,'name',None)!='a' or not node.get('href'):continue
            if node.find_parent(['nav','header','footer']):continue
            url=urljoin(base,node['href'])
            if url.startswith('http://'):url='https://'+url[len('http://'):]
            if url in seen or not official(url):continue
            seen.add(url);result.append({'url':url,'title':node.get_text(' ',strip=True) or url})
    return result


def load_prescribed(links,progress=None):
    progress=progress or (lambda percent,message:None)
    documents=[];warnings=[]
    for index,link in enumerate(links,1):
        progress(22,f'Pridobivam predpis {index}/{len(links)}: {link["title"]}')
        try:
            text=source_text(link['url']);law=parse_law(text)
            cached=LawLibrary().find_url(link['url'])
            documents.append({'kind':'law','url':cached.get('resolved_url',link['url']) if cached else link['url'],'title':link['title'],'text':text,'law':law,
                              'metadata':cached.get('metadata',{}) if cached else {}})
        except Exception as ex:
            # Exact known ID can reference a local snapshot, never infer a new file ID.
            identifiers=re.findall(r'\b(?:URED|ZAKO|PRAV)\d+\b',link['url'],re.I)
            matches=[e for e in LawLibrary().entries() if len(identifiers)==1 and e.get('source_id')==identifiers[0].upper()]
            if len(matches)==1:
                stored=LawLibrary().load(matches[0]['source_url'],matches[0]['sha256'])
                documents.append({'kind':'law','url':matches[0]['source_url'],'title':link['title'],'text':stored['text'],'law':stored['law'],'metadata':stored['metadata']})
                warnings.append(f"PREDPIS ZA PREGLED: {link['title']}: spletni vir ni dostopen; uporabljen lokalni posnetek {matches[0].get('version_label')}. Časovno veljavnost preverite.")
            else:
                reason=(f'HTTP {ex.response.status_code}' if getattr(ex,'response',None) is not None else str(ex)[:240])
                warnings.append(f"PREDPIS NI DOSTOPEN: {link['title']} · {link['url']} · {reason}. Pogoji, odvisni od tega predpisa, niso preverjeni.")
    return documents,warnings
