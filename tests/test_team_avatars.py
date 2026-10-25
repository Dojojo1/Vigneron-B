import io

from PIL import Image

from conftest import login, headers, grant, MEMBER, OTHER


def upload(env):
    image=io.BytesIO()
    Image.new('RGB',(12,12),(35,85,130)).save(image,format='PNG')
    response=env['client'].post('/api/me/avatar',files={'file':('portrait.png',image.getvalue(),'image/png')},headers=headers(env))
    assert response.status_code==200


def test_team_uses_custom_profile_photo_and_requires_team_permission(env):
    login(env,MEMBER);upload(env)
    login(env,OTHER)
    private_photo=f'/api/pages/team/avatars/{MEMBER}'
    assert env['client'].get(private_photo).status_code==403
    grant(env,'100','team')
    members=env['client'].get('/api/pages/team').json()['members']
    portrait=next(member for member in members if member['id']==MEMBER)
    other=next(member for member in members if member['id']==OTHER)
    assert portrait['avatar'].startswith(private_photo+'?v=')
    assert other['avatar'].startswith('https://cdn.discordapp.com/')
    response=env['client'].get(portrait['avatar'])
    assert response.status_code==200 and response.headers['content-type']=='image/png'
    assert response.headers['cache-control']=='no-store'
    with Image.open(io.BytesIO(response.content)) as photo:
        assert photo.getpixel((0,0))==(35,85,130)
    assert env['client'].get('/api/me/avatar').status_code==404  # Their own profile stays separate.
    env['client'].cookies.clear()
    assert env['client'].get(portrait['avatar']).status_code==401


def test_team_photo_follows_replacement_reset_and_membership(env):
    grant(env,'100','team')
    login(env,MEMBER);upload(env)
    def own_team_entry():
        return next(member for member in env['client'].get('/api/pages/team').json()['members'] if member['id']==MEMBER)
    previous=own_team_entry()['avatar']
    upload(env)
    assert own_team_entry()['avatar']!=previous
    env['client'].patch('/api/me/profile',json={'resetAvatar':True},headers=headers(env))
    assert own_team_entry()['avatar']==env['client'].get('/api/me').json()['user']['discordAvatar']
    assert env['client'].get(previous).status_code==404
    with env['store'].connect(True) as db:
        db.execute('UPDATE users SET member=0 WHERE id=?',(MEMBER,))
    login(env,OTHER)
    assert MEMBER not in [member['id'] for member in env['client'].get('/api/pages/team').json()['members']]
    assert env['client'].get(previous).status_code==404
