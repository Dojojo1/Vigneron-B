"""Le site privé ne sert aucun écran ni aucune API du setup du bot."""
from pathlib import Path


def test_site_does_not_mount_bot_setup(env):
    paths = {getattr(route, 'path', '') for route in env['app'].routes}
    assert not any(path.startswith(('/setup', '/api/setup')) for path in paths)
    for name in ('setup.html', 'setup.js', 'setup.css'):
        assert not (env['cfg'].root / 'static' / name).exists()
    home = env['client'].get('/').text
    assert 'href="/setup"' not in home


def test_setup_cookies_do_not_grant_site_access(env):
    client = env['client']
    client.cookies.set('bot_setup_session', 'cookie-du-setup')
    client.cookies.set('heritage_setup_session', 'ancien-cookie-du-setup')
    assert client.get('/api/me').status_code == 401
    assert client.get('/api/pages/stats').status_code == 401
