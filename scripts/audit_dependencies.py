"""Comparer les versions publiques du verrou à OSV, sans lire la configuration privée."""
import argparse
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request


API='https://api.osv.dev/v1/querybatch'


def audit(lockfile):
    packages=[]
    for line in lockfile.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'): continue
        match=re.fullmatch(r'([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)',line)
        if not match: raise ValueError('Le verrou doit contenir uniquement des noms et versions publics épinglés.')
        packages.append({'package':{'ecosystem':'PyPI','name':match[1]},'version':match[2]})
    if not packages: raise ValueError('Aucune dépendance à vérifier.')
    pending=list(enumerate(packages));findings={};calls=0
    while pending:
        if calls>=10: raise ValueError('Pagination OSV excessive : audit interrompu sans conclusion.')
        request=urllib.request.Request(API,data=json.dumps({'queries':[query for _,query in pending]}).encode(),
                                       headers={'Content-Type':'application/json','User-Agent':'Heritage-local-audit/1'},method='POST')
        with urllib.request.urlopen(request,timeout=30) as response:
            body=response.read(8*1024*1024+1)
            if len(body)>8*1024*1024: raise ValueError('Réponse OSV trop volumineuse.')
            result=json.loads(body)
        if not isinstance(result,dict) or not isinstance(result.get('results'),list) or len(result['results'])!=len(pending):
            raise ValueError('Réponse OSV incomplète : aucun résultat de sécurité validé.')
        following=[]
        for (index,query),entry in zip(pending,result['results']):
            if not isinstance(entry,dict) or not isinstance(entry.get('vulns',[]),list): raise ValueError('Réponse OSV invalide.')
            for vulnerability in entry.get('vulns',[]):
                if not isinstance(vulnerability,dict) or not isinstance(vulnerability.get('id'),str): raise ValueError('Avis OSV invalide.')
                findings.setdefault(packages[index]['package']['name'],set()).add(vulnerability['id'])
            token=entry.get('next_page_token')
            if token:
                if not isinstance(token,str): raise ValueError('Pagination OSV invalide.')
                following.append((index,{**query,'page_token':token}))
        pending=following;calls+=1
    return {'source':API,'packagesChecked':len(packages),'calls':calls,
            'findings':{name:sorted(ids) for name,ids in sorted(findings.items())}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lockfile',type=Path,default=Path(__file__).resolve().parents[1]/'requirements.lock')
    parser.add_argument('--json-output',type=Path)
    args=parser.parse_args()
    try: report=audit(args.lockfile)
    except (OSError,ValueError,urllib.error.URLError) as error:
        print(json.dumps({'ok':False,'error':'Audit des dépendances incomplet. Vérifier la connexion et le verrou.','category':type(error).__name__}))
        return 2
    if args.json_output: args.json_output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 1 if report['findings'] else 0


if __name__=='__main__':sys.exit(main())
