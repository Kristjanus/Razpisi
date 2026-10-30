"""Select bounded scoring sections locally; never fall back to sending all criteria."""
import re
import unicodedata


def normalize(text):
    return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',text)).strip().casefold()


def intervention_codes(text):
    return {str(int(code)) for code in re.findall(r'\bIRP\s*[-–]?\s*(\d{1,3})\b',text,re.I)}


def is_criteria(doc):
    return bool(re.search(r'merila',doc.get('title','')+' '+doc.get('url',''),re.I))


def annotate_pages(pages, toc):
    valid=[entry[:3] for entry in toc if 1<=entry[2]<=len(pages)]
    # Some PDFs have only a printed contents page, without PDF bookmarks.
    if not valid:
        for page in pages:
            for line in page['text'].splitlines():
                match=re.fullmatch(r'\s*(\d+(?:\.\d+){0,3})[.)]?\s+([A-ZČŠŽ][^\n]{11,160})\s*',line)
                if match and not re.search(r'\.{3}|\s\d+\s*$',match[2]):
                    valid.append([match[1].count('.')+1,line.strip(),page['number']])
    sections=[]
    for index,(level,title,start) in enumerate(valid):
        stop=next((entry[2] for entry in valid[index+1:] if entry[0]<=level and entry[2]>=start),len(pages)+1)
        sections.append(dict(title=title,start=start,end=min(stop,len(pages)),level=level))
    for page in pages:
        page['sections']=[s for s in sections if s['start']<=page['number']<=s['end']]
    return pages


def select_documents(docs, references=None):
    references=references or []
    selected=[];warnings=[]
    for doc in docs:
        if not is_criteria(doc):
            selected.append(doc);continue
        pages=doc.get('page_texts',[])
        sections={ (s['title'],s['start'],s['end']):s for p in pages for s in p.get('sections',[]) }
        matched=[];used=[]
        for ref in references:
            anchor=normalize(ref['anchor'])
            codes=intervention_codes(anchor)
            choices=[s for s in sections.values() if
                     (len(anchor)>=12 and (anchor in normalize(s['title']) or normalize(s['title']) in anchor))
                     or (codes and codes==intervention_codes(s['title']))]
            if choices:
                matched.extend(choices);used.append(ref)
        if not matched:
            warnings.append(f"NEPOPOLNA ANALIZA: {doc['title']}: z dokazljivimi sklici ni mogoče določiti ustrezne tabele ali razdelka. Dokument meril NI poslan AI-ju. Minimalni prag preverite ročno.")
            continue
        numbers={n for s in matched for n in range(s['start'],s['end']+1)}
        # Retain explicitly labelled shared rules, but not arbitrary other chapters.
        common=[s for s in sections.values() if re.search(r'skupn|splošn',s['title'],re.I) and not intervention_codes(s['title'])]
        numbers.update(n for s in common for n in range(s['start'],s['end']+1))
        unresolved=[]
        # Resolve explicit numbered cross-references locally; do not send whole book.
        for _ in range(len(sections)+1):
            added=set()
            for page in pages:
                if page['number'] not in numbers:continue
                for section_id in re.findall(r'(?:poglavj\w*|razdel\w*|točk\w*|tabel\w*)\s+(\d+(?:\.\d+)+)',page['text'],re.I):
                    targets=[s for s in sections.values() if re.match(r'^\s*'+re.escape(section_id)+r'(?:[.)\s]|$)',s['title'])]
                    if targets:
                        added.update(n for s in targets for n in range(s['start'],s['end']+1))
                    else:unresolved.append(section_id)
            if added<=numbers:break
            numbers.update(added)
        keep=[p for p in pages if p['number'] in numbers]
        # Ambiguous heading matches must never cause a full-book API call.
        if not keep or (len(keep)==len(pages) and len(pages)>20):
            warnings.append(f"NEPOPOLNA ANALIZA: {doc['title']}: izbor bi zajel celoten dokument; merila NI poslana AI-ju. Potreben je ročni izbor razdelka.")
            continue
        selected.append({**doc,'page_texts':keep,'text':'\n'.join(f'[STRAN {p["number"]}]\n{p["text"]}' for p in keep),
                         'selected_pages':[p['number'] for p in keep],'selection_references':used})
        warnings.append(f"Merila: {doc['title']}: AI-ju poslanih {len(keep)}/{len(pages)} strani na podlagi sklicev v drugih dokumentih. Različico in sklop potrdite ročno.")
        if unresolved:
            warnings.append(f"NEPOPOLNA ANALIZA: {doc['title']}: nerešeni sklici {', '.join(sorted(set(unresolved)))}. Dodatne opombe preverite ročno.")
    return selected,warnings
