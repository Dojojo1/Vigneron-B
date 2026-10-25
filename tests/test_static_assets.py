"""Le point d’entrée doit rester autonome, sans fichier statique manquant."""
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


STATIC = Path(__file__).resolve().parents[1] / 'static'


class EntryAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
        self.ids = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids.append(attrs['id'])
        attribute = {'link': 'href', 'script': 'src'}.get(tag)
        if attribute and attrs.get(attribute):
            self.urls.append(attrs[attribute])


def test_entry_and_stylesheets_reference_existing_local_assets():
    entry = EntryAssets()
    entry.feed((STATIC / 'index.html').read_text())
    missing = []
    for url in entry.urls:
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc:
            continue
        asset = STATIC / unquote(parsed.path)
        if not asset.is_file():
            missing.append(url)
        elif asset.suffix == '.css':
            for value in re.findall(r'''url\(\s*['"]?([^\)'"\s]+)''', asset.read_text()):
                target = urlsplit(value)
                if target.scheme or target.netloc or not target.path:
                    continue
                if not (asset.parent / unquote(target.path)).is_file():
                    missing.append(f'{asset.name}: {value}')
    assert not missing, missing


def test_entry_has_unique_element_identifiers():
    entry = EntryAssets()
    entry.feed((STATIC / 'index.html').read_text())
    assert not [value for value, count in Counter(entry.ids).items() if count > 1]
