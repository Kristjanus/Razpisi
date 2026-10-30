"""Discover call pages linked from the official SKP listing only."""
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from analyzer import allowed, get

SOURCE_URL = 'https://www.gov.si/zbirke/projekti-in-programi/skupna-kmetijska-politika/javni-razpisi/'


def call_url(url):
    parsed = urlparse(url)
    return (allowed(url) and parsed.hostname in ('gov.si', 'www.gov.si')
            and parsed.path.startswith('/zbirke/javne-objave/')
            and bool(parsed.path[len('/zbirke/javne-objave/'):].strip('/')))


def discover(raw, base=SOURCE_URL):
    soup = BeautifulSoup(raw, 'html.parser')
    for node in soup(['nav', 'header', 'footer']):
        node.decompose()
    content = soup.select_one('main') or soup.select_one('article') or soup
    links = {}
    for anchor in content.select('a[href]'):
        url = urljoin(base, anchor['href']).split('#')[0]
        title = ' '.join(anchor.get_text(' ', strip=True).split())
        # Index membership supplies SKP scope; call wording excludes guidance.
        wording = (title+' '+urlparse(url).path).lower().replace('-', ' ')
        if call_url(url) and re.search(r'\bjavni\s+(?:razpis|poziv)\b', wording):
            links[url] = title or urlparse(url).path.rstrip('/').split('/')[-1].replace('-', ' ')
    return links


def load_calls():
    final, raw, _ = get(SOURCE_URL)
    links = discover(raw, final)
    if not links:
        raise ValueError('Uradni seznam SKP ni vrnil povezav do razpisov; preverite strukturo strani. Stari zapisi so ohranjeni.')
    return links


def listed_call(url):
    canonical = lambda value: value.rstrip('/')
    return call_url(url) and canonical(url) in {canonical(u) for u in load_calls()}
