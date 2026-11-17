"""Only signed, dated, deduplicated coffre logs can affect the selected check."""
import json
import secrets
import sqlite3

from conftest import SUPREME, login
from backend.coffre import Coffre
from test_bot_connection import configure, signed
from test_business_connection import sale
from scripts.seed_coffre_check import SALE_IDS, seed
from scripts.seed_coffre_legacy_recoveries import seed as seed_legacy


PATH = '/internal/bot/events'


def log(message='1571982221206884475', source='1571982219969429667:0', **changes):
    return {'channelId': '1567451843838083082', 'messageId': message,
            'sourceMessageId': source, 'eventTime': '2026-11-16T21:15:13+01:00',
            'action': 'retrait', 'itemId': 'saleMoney', 'amount': 1000000,
            'playerName': 'Profil test', 'playerDiscord': '123',
            'sourceUrl': 'https://discord.com/channels/932301610128912414/1219050172060008458/' + source.split(':')[0],
            **changes}


def send(env, record, event_id=None):
    return signed(env, 'POST', PATH, {'guildId': env['cfg'].guild_id,
                  'eventId': event_id or secrets.token_hex(16), 'kind': 'coffre_log', 'log': record})


def test_signed_coffre_log_is_private_deduplicated_and_excludable(env):
    configure(env)
    first = log()
    assert send(env, first).status_code == 200
    assert send(env, first).json()['duplicate'] is True
    assert send(env, log(amount=2000000)).status_code == 409
    assert send(env, log(message='1571982221206884476',source='1571982219969429668:0',
                         eventTime='2026-11-15T21:15:13+01:00')).status_code == 400
    assert env['client'].get('/api/pages/logs').status_code == 401
    login(env, SUPREME)
    with env['store'].connect(True) as db:
        db.execute('INSERT INTO coffre_log_exclusions VALUES(?,?,?)',
                   (first['messageId'], 'Fonds antérieurs', None))
    result = env['client'].get('/api/pages/logs?view=screen').json()
    assert len(result['entries']) == 1
    assert result['entries'][0]['exclusionReason'] == 'Fonds antérieurs'
    assert result['pagination']['logs']['total'] == 1


def test_two_selected_sales_only_flag_proven_overcount(env):
    configure(env)
    login(env, SUPREME)
    state = env['store'].read_domain()
    sample = sale(id='sale-a', treated=0, botStatus='confirmed')
    state['sales'] = [sample, {**sample, 'id': 'sale-b'}]
    state['machines'] = []
    with env['store'].connect(True) as db:
        db.execute('UPDATE domain_store SET body=? WHERE id=1', (json.dumps(state),))
        db.executemany('INSERT INTO coffre_checks VALUES(?,?,?,?)',
                       [('sale-a', 1794870000, 0, 5000000), ('sale-b', 1794870000, 0, 5000000)])
    check = Coffre(env['store']).check(state)
    assert check['status'] == 'waiting'
    state['sales'][0]['treated'] = 1000000
    with env['store'].connect(True) as db:
        db.execute('UPDATE domain_store SET body=? WHERE id=1', (json.dumps(state),))
    check = Coffre(env['store']).check(state)
    assert check['status'] == 'mismatch' and check['treatedDelta'] == 1000000
    assert check['tracked'][0]['issue'] == {'unexplained': 1000000, 'available': 0}
    state['machines'] = [{'id': 'machine-a', 'amount': 1000000, 'recovered': True,
                          'start': 1794870001000, 'recoveredAt': 1794870100000,
                          'botStatus': 'confirmed'}]
    with env['store'].connect(True) as db:
        db.execute('UPDATE domain_store SET body=? WHERE id=1', (json.dumps(state),))
    check = Coffre(env['store']).check(state)
    assert check['status'] == 'matched'
    assert check['cleanRecoveredAmount'] == 800000
    assert all('issue' not in entry for entry in check['tracked'])


def test_signed_alert_read_returns_only_proven_dossier_issues(env):
    configure(env)
    path = '/internal/bot/coffre-alert'
    assert env['client'].get(path).status_code == 403
    state = env['store'].read_domain()
    sample = sale(id='1571966486782939269', treated=1000000, botStatus='confirmed')
    state['sales'] = [sample, {**sample, 'id': '1571966567963435083', 'treated': 0}]
    state['machines'] = []
    with env['store'].connect(True) as db:
        db.execute('UPDATE domain_store SET body=? WHERE id=1', (json.dumps(state),))
        db.executemany('INSERT INTO coffre_checks VALUES(?,?,?,?)',
                       [(row['id'], 1794870000, 0, 5000000) for row in state['sales']])
    response = signed(env, 'GET', path)
    assert response.status_code == 200
    result = response.json()
    assert result['status'] == 'mismatch'
    assert result['issues'] == [{'id': sample['id'], 'delta': 1000000,
                                 'unexplained': 1000000, 'available': 0}]
    with env['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM bot_commands').fetchone()[0] == 0


def test_old_launch_recovered_after_cutoff_is_not_attributed_to_new_sales(env):
    configure(env)
    state = env['store'].read_domain()
    sample = sale(id='sale-a', treated=900000, botStatus='confirmed')
    state['sales'] = [sample, {**sample, 'id': 'sale-b', 'treated': 0}]
    state['machines'] = [
        {'id': 'old', 'amount': 1000000, 'start': 1794869000000,
         'recoveredAt': 1794870200000, 'recovered': True, 'botStatus': 'confirmed'},
        {'id': 'new', 'amount': 900000, 'start': 1794870010000,
         'recoveredAt': 1794870300000, 'recovered': True, 'botStatus': 'confirmed'},
    ]
    with env['store'].connect(True) as db:
        db.executemany('INSERT INTO coffre_checks VALUES(?,?,?,?)',
                       [('sale-a', 1794870000, 0, 5000000), ('sale-b', 1794870000, 0, 5000000)])
    check = Coffre(env['store']).check(state)
    assert check['status'] == 'matched'
    assert check['recoveredAmount'] == 900000
    assert check['cleanRecoveredAmount'] == 720000
    assert check['coffreMovements']['money'] == 0  # A direct handoff needs no deposit.
    state['sales'][1]['treated'] = 100000
    check = Coffre(env['store']).check(state)
    assert check['status'] == 'mismatch'
    assert 'issue' not in check['tracked'][0]
    assert check['tracked'][1]['issue'] == {'unexplained': 100000, 'available': 0}


def test_known_undated_recoveries_are_frozen_but_new_ones_block_check(env):
    configure(env)
    state = env['store'].read_domain()
    sample = sale(id='sale-a', treated=0, botStatus='confirmed')
    state['sales'] = [sample]
    old = {'id': 'old', 'amount': 1000000, 'recovered': True,
           'recoveredAt': None, 'botStatus': 'confirmed'}
    state['machines'] = [old]
    with env['store'].connect(True) as db:
        db.execute('UPDATE domain_store SET body=? WHERE id=1', (json.dumps(state),))
        db.execute('INSERT INTO coffre_checks VALUES(?,?,?,?)', ('sale-a', 1794870000, 0, 5000000))
    (env['store'].path.parent / 'backups').mkdir(exist_ok=True)
    backup, count = seed_legacy(env['store'].path)
    assert backup.is_file() and count == 1
    assert Coffre(env['store']).check(state)['status'] == 'waiting'
    state['machines'].append({**old, 'id': 'new'})
    assert Coffre(env['store']).check(state)['status'] == 'unavailable'


def test_baseline_is_backed_up_and_cannot_overwrite_existing_configuration(tmp_path):
    database = tmp_path / 'heritage-test.sqlite3'
    (tmp_path / 'backups').mkdir()
    records = [sale(id=identifier, created=1794856400000, treated=0, botStatus='confirmed')
               for identifier in SALE_IDS]
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE domain_store(id INTEGER PRIMARY KEY,body TEXT NOT NULL)')
        db.execute('INSERT INTO domain_store VALUES(1,?)', (json.dumps({'sales': records}),))
    backup = seed(database)
    assert backup.is_file()
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT count(*) FROM coffre_checks').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM coffre_log_exclusions').fetchone()[0] == 3
    try:
        seed(database)
    except ValueError:
        pass
    else:
        raise AssertionError('A second baseline must not replace the first one')
