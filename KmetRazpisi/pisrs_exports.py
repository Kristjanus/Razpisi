"""Resolve observed PISRS record URLs to explicitly known export URLs.

File IDs are opaque. These two hints were supplied by the user, not inferred.
Every resolved download must subsequently prove its act ID in the export.
"""
import re
from urllib.parse import urlparse,parse_qs
from law_documents import LawParseError

KNOWN_EXPORTS={
    'URED8874':'https://pisrs.si/api/datoteke/integracije/493126267',
    'URED9278':'https://pisrs.si/api/datoteke/integracije/545935768',
}


def record_id(url):
    parsed=urlparse(url)
    if parsed.hostname not in ('pisrs.si','www.pisrs.si'):return None
    query=parse_qs(parsed.query)
    value=next((values[0] for key,values in query.items() if key.casefold()=='id' and values),'')
    return value.upper() if re.fullmatch(r'(?:URED|ZAKO|PRAV)\d+',value,re.I) else None


def direct_export(url):
    parsed=urlparse(url)
    return parsed.scheme=='https' and parsed.hostname in ('pisrs.si','www.pisrs.si') and bool(re.fullmatch(r'/api/datoteke/integracije/\d+/?',parsed.path))


def resolve_export(url,entries=()):
    identifier=record_id(url)
    if not identifier:
        return url,next((key for key,value in KNOWN_EXPORTS.items() if value==url),None)
    known=[e for e in entries if e.get('source_id')==identifier]
    exports={(e.get('resolved_url') or e['source_url'],e.get('version_label')) for e in known if direct_export(e.get('resolved_url') or e['source_url'])}
    if len(exports)>1:raise LawParseError(f'{identifier}: shranjenih je več različic izvoza; potrebno je določiti različico za razpis')
    if len(exports)==1:return next(iter(exports))[0],identifier
    return KNOWN_EXPORTS.get(identifier,url),identifier
