"""Conservative selection of bookmarked intervention sections in shared criteria."""
import re


def intervention_codes(text):
    return set(re.findall(r'\bIRP\s*[-–]?\s*(\d{1,3})\b',text,re.I))


def annotate_pages(pages, toc):
    sections=[]
    for index,(level,title,start,*_) in enumerate(toc):
        codes=intervention_codes(title)
        if not codes or start<1:
            continue
        stop=next((entry[2] for entry in toc[index+1:] if entry[0]<=level and entry[2]>=start),len(pages)+1)
        sections.append((start,stop,codes))
    if len(set().union(*(s[2] for s in sections)))<2:
        return pages
    for page in pages:
        number=page['number']
        # Include boundary pages in both scopes: headings can begin mid-page.
        page['common_heading']=any(entry[2]==number and not intervention_codes(entry[1]) for entry in toc)
        page['intervention_codes']=sorted(set().union(*(codes for start,stop,codes in sections if start<=number<=stop)))
    return pages


def select_documents(docs):
    primary=[d for d in docs if not re.search(r'merila',d['title'],re.I)]
    context='\n'.join(d['text'] for d in primary)
    codes=intervention_codes(context)
    selected=[];warnings=[]
    for doc in docs:
        pages=doc.get('page_texts',[])
        if not re.search(r'merila',doc['title'],re.I):
            selected.append(doc);continue
        if len(codes)!=1 or not pages or any('intervention_codes' not in p for p in pages):
            selected.append(doc)
            warnings.append(f"Merila: {doc['title']}: ustreznega razdelka ni mogoče zanesljivo omejiti; prebran bo celoten dokument. Veljavno različico in sklop preverite ročno.")
            continue
        code=next(iter(codes))
        relevant=[p for p in pages if code in p['intervention_codes']]
        if not relevant:
            selected.append(doc)
            warnings.append(f"Merila: {doc['title']}: ni razdelka IRP{code}; potreben je ročni pregled povezave med razpisom in merili. Prebran bo celoten dokument.")
            continue
        # Cross-section references need full-document context rather than guessing.
        if any(re.search(r'(?:poglavj|razdel|prilog|sklic)',p['text'],re.I) for p in relevant):
            selected.append(doc)
            warnings.append(f"Merila: {doc['title']}: razdelek IRP{code} vsebuje dodatne sklice; za ohranitev konteksta bo prebran celoten dokument.")
            continue
        keep=[p for p in pages if not p['intervention_codes'] or p.get('common_heading') or code in p['intervention_codes']]
        selected.append({**doc,'page_texts':keep,'text':'\n'.join(f'[STRAN {p["number"]}]\n{p["text"]}' for p in keep),
                         'selected_pages':[p['number'] for p in keep]})
        warnings.append(f"Merila: {doc['title']}: izbran IRP{code} in skupne strani, {len(keep)}/{len(pages)} strani. Različico, sklop in uporabo meril še potrdite ročno.")
    return selected,warnings
