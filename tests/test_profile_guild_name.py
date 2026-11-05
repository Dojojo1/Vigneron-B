"""Discord names stay authoritative despite a legacy site alias."""
import json

from conftest import MEMBER, SUPREME, grant, headers, login


def test_team_and_audit_use_member_nickname_instead_of_legacy_alias(env):
    provider=env['provider'];original=provider.member
    async def member(user_id):
        return {**await original(user_id),'nick':'Surnom du domaine' if user_id==MEMBER else 'Direction'}
    provider.member=member
    login(env)
    with env['store'].connect(True) as db:
        db.execute('UPDATE users SET display_name=? WHERE id=?',('Ancien pseudo',MEMBER))
    grant(env,'100','team');grant(env,'100','machines')
    account=env['client'].get('/api/me').json()['user']
    assert account['displayName']==account['discordName']=='Surnom du domaine'
    assert account['customName'] is None and account['nameEditable'] is False
    team=env['client'].get('/api/pages/team').json()['members']
    assert next(row for row in team if row['id']==MEMBER)['displayName']=='Surnom du domaine'
    with env['store'].connect(True) as db:
        env['store'].audit(db,MEMBER,'name_verified',{'page':'profile'})
    with env['store'].connect() as db:
        detail=json.loads(db.execute("SELECT detail FROM audit WHERE kind='name_verified'").fetchone()[0])
    assert detail['actorName']=='Surnom du domaine'
    assert env['store'].read_user(MEMBER)['display_name']=='Ancien pseudo'
    login(env,SUPREME)
    accounts=env['client'].get('/api/admin/users').json()['users']
    displayed=next(row for row in accounts if row['id']==MEMBER)
    assert displayed['siteAccess']['displayName']=='Surnom du domaine'
    assert displayed['display_name'] is None and displayed['username']=='Surnom du domaine'


def test_profile_name_cannot_impersonate_another_member_but_photos_remain_independent(env):
    login(env)
    response=env['client'].patch('/api/me/profile',json={'displayName':'Quelqu’un d’autre'},headers=headers(env))
    assert response.status_code==400
    assert 'serveur Discord' in response.json()['detail']
    assert env['store'].read_user(MEMBER)['display_name'] is None
    response=env['client'].patch('/api/me/profile',json={'displayName':'Membre du domaine','resetAvatar':True},headers=headers(env))
    assert response.status_code==200
    assert response.json()['user']['displayName']=='Membre du domaine'
