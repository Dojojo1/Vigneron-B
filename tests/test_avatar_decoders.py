"""Les photos ne doivent jamais activer des décodeurs hors des formats autorisés."""
import io

import pytest
from PIL import Image

from conftest import headers, login


@pytest.mark.parametrize('format', ['PNG', 'JPEG', 'WEBP'])
def test_permitted_photo_formats_are_decoded_and_normalized(env, format):
    login(env)
    raw=io.BytesIO();Image.new('RGB',(24,18),'#294250').save(raw,format=format)
    result=env['client'].post('/api/me/avatar',files={'file':('portrait.bin',raw.getvalue(),'application/octet-stream')},headers=headers(env))
    assert result.status_code==200
    response=env['client'].get('/api/me/avatar')
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.format=='PNG' and image.size==(24,18)


def test_unsupported_decoder_is_not_invoked_even_with_disguised_filename(env, monkeypatch):
    login(env)
    raw=io.BytesIO();Image.new('RGB',(24,18),'blue').save(raw,format='TIFF')
    Image.init()
    factory,accept=Image.OPEN['TIFF']
    called=[]
    def forbidden_factory(*args,**kwargs):
        called.append(True)
        raise AssertionError('Le décodeur TIFF ne doit pas être activé.')
    monkeypatch.setitem(Image.OPEN,'TIFF',(forbidden_factory,accept))
    before=env['store'].read_user('111111111111111111')['avatar_file']
    result=env['client'].post('/api/me/avatar',files={'file':('portrait.png',raw.getvalue(),'image/png')},headers=headers(env))
    assert result.status_code==400 and called==[]
    assert env['store'].read_user('111111111111111111')['avatar_file']==before
