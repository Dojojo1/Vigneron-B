"""Regenerate the GitHub Pages entry from the server interface (standard library only)."""
from pathlib import Path


def sync():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'static/index.html').read_text(encoding='utf-8')
    # Keep charset first, then resolve every asset under the project subpath.
    entry = source.replace(
        '<meta charset="utf-8">',
        '<meta charset="utf-8">\n<base href="./static/">\n'
        '<meta name="heritage-hosting" content="github-pages">',
        1,
    )
    (root / 'index.html').write_text(entry, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    sync()
    print('GitHub Pages entry updated.')
