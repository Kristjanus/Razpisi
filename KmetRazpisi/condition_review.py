"""Conservative duplicate removal; retain evidence and distinct scopes."""
import json
import re
import unicodedata


def normalize(value):
    return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',str(value))).strip().casefold().rstrip('.; ')


def deduplicate(conditions):
    output=[];seen={}
    for condition in conditions:
        evidence=condition.get('evidence_quote','')
        numbers=tuple(sorted(set(re.findall(r'\b\d+(?:[.,]\d+)?\b',evidence))))
        scope=tuple(sorted(set(re.findall(r'\b(?:sklop\w*\s+\w+|enostavn\w*|zahtevn\w*|razen[^.;]+)',evidence,re.I))))
        legal=condition.get('legal_resolution') or {}
        provisions=tuple((p.get('source_url'),p.get('provision')) for p in legal.get('provisions',[]))
        label=normalize(condition.get('label','')).replace('mora imeti','ima').replace('oziroma','ali')
        key=(label,condition.get('fact_key'),condition.get('operator'),
             json.dumps(condition.get('expected'),sort_keys=True,ensure_ascii=False),bool(condition.get('mandatory')),bool(condition.get('fixed')),numbers,scope,provisions)
        if key not in seen:
            item={**condition,'additional_sources':list(condition.get('additional_sources',[]))}
            seen[key]=item;output.append(item);continue
        target=seen[key]
        source={k:condition.get(k) for k in ('evidence_url','evidence_quote','document_title','page_number')}
        primary={k:target.get(k) for k in source}
        if source!=primary and source not in target['additional_sources']:target['additional_sources'].append(source)
        for source in condition.get('additional_sources',[]):
            if source not in target['additional_sources']:target['additional_sources'].append(source)
    return output
