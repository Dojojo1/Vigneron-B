import re

def discover_pages(static_dir):
    source = (static_dir / 'app.js').read_text(encoding='utf-8')
    declaration = re.search(r'const pages=\{(.*?)\};',source,re.S)
    if not declaration: raise RuntimeError('Registre de pages introuvable dans app.js')
    pages = {match[0]: {'id':match[0],'label':match[1],'kind':'private'}
             for match in re.findall(r"([a-zA-Z][\w-]*):\['([^']+)'",declaration.group(1))}
    pages['profile'] = {'id':'profile','label':'Mon Registre','kind':'member'}
    pages['council'] = {'id':'council','label':'Le Conseil des Accès','kind':'supreme'}
    return pages
