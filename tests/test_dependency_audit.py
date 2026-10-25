"""Un audit OSV partiel ou inaccessible ne doit jamais annoncer un résultat sain."""
import io
import json
import sys
import urllib.error

import pytest

from scripts import audit_dependencies as checker


def lock(tmp_path,content='pillow==13.0.0\ncryptography==50.0.2\n'):
    path=tmp_path/'requirements.lock';path.write_text(content);return path


def test_pagination_preserves_all_advisories_and_package_order(tmp_path,monkeypatch):
    calls=[]
    responses=[{'results':[{'vulns':[{'id':'TEST-1'}],'next_page_token':'second'},{}]},
               {'results':[{'vulns':[{'id':'TEST-2'},{'id':'TEST-1'}]}]}]
    def reply(request,timeout):
        calls.append(json.loads(request.data));return io.BytesIO(json.dumps(responses.pop(0)).encode())
    monkeypatch.setattr(checker.urllib.request,'urlopen',reply)
    result=checker.audit(lock(tmp_path))
    assert result['packagesChecked']==2 and result['calls']==2
    assert result['findings']=={'pillow':['TEST-1','TEST-2']}
    assert calls[1]['queries']==[{**calls[0]['queries'][0],'page_token':'second'}]


def test_incomplete_osv_response_is_an_error_not_a_clean_result(tmp_path,monkeypatch):
    monkeypatch.setattr(checker.urllib.request,'urlopen',lambda *a,**kw:io.BytesIO(b'{"results":[{}]}'))
    with pytest.raises(ValueError,match='incomplète'):checker.audit(lock(tmp_path))


def test_private_requirement_urls_are_never_transmitted(tmp_path,monkeypatch):
    def unexpected(*args,**kwargs):raise AssertionError('Aucun appel réseau avec un verrou non public.')
    monkeypatch.setattr(checker.urllib.request,'urlopen',unexpected)
    with pytest.raises(ValueError,match='publics'):
        checker.audit(lock(tmp_path,'package @ https://user:fake-test-password@example.invalid/package.whl'))


def test_network_failure_reports_incomplete_audit_without_raw_details(tmp_path,monkeypatch,capsys):
    def unavailable(*args,**kwargs):raise urllib.error.URLError('RAW_NETWORK_INTERNAL_DETAILS')
    monkeypatch.setattr(checker.urllib.request,'urlopen',unavailable)
    monkeypatch.setattr(sys,'argv',['audit_dependencies.py','--lockfile',str(lock(tmp_path))])
    assert checker.main()==2
    report=capsys.readouterr().out
    assert json.loads(report)['ok'] is False
    assert 'RAW_NETWORK_INTERNAL_DETAILS' not in report
