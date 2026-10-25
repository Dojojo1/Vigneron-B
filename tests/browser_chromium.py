"""Audit Chrome/Chromium isolé, protocole WebDriver HTTP sans Selenium.

Exemple (binaires Chrome for Testing de même version, téléchargés hors du dépôt) :
  .venv/bin/python tests/browser_chromium.py \
    --chrome-binary /tmp/chrome-headless-shell-linux64/chrome-headless-shell \
    --driver-binary /tmp/chromedriver-linux64/chromedriver --workflows

CHROME_BINARY et CHROMEDRIVER_BINARY peuvent remplacer ces deux arguments.
--no-sandbox est explicite, pour un environnement de test qui l'exige ; le test
n'ouvre que son serveur loopback éphémère et bloque les ressources extérieures.
Ni .env, ni base active, ni API Discord/Google ne sont utilisés.
Le script émet un objet JSON mesuré et renvoie un code non nul en cas d'échec.
"""
import argparse
import base64
import json
import os
import shlex
from pathlib import Path
import socket
import signal
import subprocess
import sys
import tempfile
import threading
import time

import httpx

PROJECT = Path(__file__).resolve().parents[1]
ROUTES = {
    'overview': '.night-metrics', 'sales': '.sales-dossiers',
    'machines': '.machine-history', 'tombola': '.raffle-grid',
    'history': '.history-table', 'stats': '.stats-top',
    'journal': '.journal-panel', 'team': '.team-grid',
    'profile': '#secure-profile-form', 'council': '.access-matrix-panel',
}


class WebDriver:
    def __init__(self, origin):
        self.client = httpx.Client(base_url=origin, timeout=35, trust_env=False)
        self.session = None

    def command(self, method, path, data=None, *, session=True, timeout=None):
        prefix = '/session/' + self.session if session else ''
        options={'timeout':timeout} if timeout is not None else {}
        response = self.client.request(method, prefix + path, json=data, **options)
        payload = response.json().get('value')
        if response.is_error or isinstance(payload, dict) and payload.get('error'):
            raise RuntimeError('WebDriver : ' + str(payload)[:600])
        return payload

    def start(self, binary, profile, no_sandbox, *, startup_timeout=75, debug_transport='port'):
        arguments = [
            '--disable-dev-shm-usage', '--no-first-run',
            '--no-default-browser-check', '--disable-background-networking',
            '--disable-component-update', '--disable-default-apps', '--disable-extensions',
            '--disable-sync', '--metrics-recording-only', '--password-store=basic',
            '--use-mock-keychain', '--window-size=1440,1000', '--enable-logging', '--v=1',
            '--user-data-dir=' + str(profile),
            '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1',
        ]
        # Headless Shell est déjà un navigateur headless distinct ; le flag
        # "new" concerne le mode unifié du binaire Chrome complet.
        if 'headless-shell' not in binary.name:
            arguments.append('--headless=new')
        else:
            # Le Shell lancé sans URL ne crée aucun onglet ; ChromeDriver attend
            # alors indéfiniment Target.getTargets. Ouvrir une page blanche dans
            # un lanceur temporaire, sans toucher au binaire officiel.
            launcher=profile.parent/'chrome-headless-shell-launcher'
            launcher.write_text('#!/bin/sh\nexec '+shlex.quote(str(binary))+' "$@" about:blank\n')
            launcher.chmod(0o700)
            binary=launcher
        arguments.append('--remote-debugging-pipe' if debug_transport=='pipe' else '--remote-debugging-port=0')
        if no_sandbox:
            arguments.append('--no-sandbox')
        try:
            payload = self.command('POST', '/session', {'capabilities': {'alwaysMatch': {
                'browserName': 'chrome', 'goog:loggingPrefs': {'browser': 'ALL'},
                'goog:chromeOptions': {'binary': str(binary), 'args': arguments},
            }}}, session=False, timeout=startup_timeout)
        except httpx.ReadTimeout:
            raise RuntimeError(f'ChromeDriver n’a pas créé la session en {startup_timeout:g} s. Consulte chromedriver.log et chrome.log ; aucun scénario de page n’a commencé.') from None
        self.session = payload['sessionId']
        return payload['capabilities']

    def script(self, code, *args):
        return self.command('POST', '/execute/sync', {'script': code, 'args': list(args)})

    def cdp(self, name, **params):
        return self.command('POST', '/goog/cdp/execute', {'cmd': name, 'params': params})

    def wait(self, code, *args, timeout=15):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            result = self.script(code, *args)
            if result:
                return result
            time.sleep(.05)
        raise AssertionError('Délai dépassé : ' + code[:180])

    def close(self):
        try:
            if self.session:
                self.command('DELETE', '')
        finally:
            self.client.close()


def free_port():
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        return reservation.getsockname()[1]


def build_fixture(root):
    sys.path.insert(0, str(PROJECT))
    from backend.app import create_app
    from backend.config import Settings
    from backend import domain

    class NoExternalAPI:
        def __getattr__(self, name):
            async def denied(*args, **kwargs):
                raise AssertionError('Un test local ne doit pas appeler Discord : ' + name)
            return denied

    (root / 'static').symlink_to(PROJECT / 'static', target_is_directory=True)
    cfg = Settings(root=root, local_preview=True, visitor_per_minute=1000,
                   visitor_writes_per_minute=1000)
    app = create_app(cfg, NoExternalAPI())
    fixture = domain.seed()
    sale, machine = fixture['sales'][0], fixture['machines'][0]
    fixture['sales'] = [{**sale, 'id': str(index), 'created': sale['created'] + index,
                         'amount': 1000, 'giver': str(900000 + index),
                         'archive': None if index < 75 else '2025-s42'} for index in range(120)]
    fixture['salesWeek']['archives'] = [{'name': '2025-s42', 'year': 2025, 'week': 42}]
    fixture['machines'] = [{**machine, 'id': str(index), 'start': machine['start'] + index,
                            'recovered': index != 0} for index in range(80)]
    fixture['events'] = [{'id': str(index), 'title': 'Opération de test', 'detail': 'Donnée fictive',
                          'author': 'Employé de test', 'page': 'machines',
                          'created': sale['created'] + index} for index in range(90)]
    today = domain.datetime.now(domain.TZ)
    week = (today.date() - domain.timedelta(days=today.weekday())).isoformat()
    fixture['tombolaRecords'] = [{'id': 'chromium-fixture', 'week': week, 'vehicles': [
        {'type': 'voiture', 'name': 'Windsor', 'price': None, 'paid': False, 'bought': False},
        {'type': 'moto', 'name': 'Bati', 'price': 1000, 'paid': False, 'bought': False},
    ]}]
    fixture['machineStats'] = {'week_start': week, 'users': {}, 'history': {
        'old': {'week_start': '2026-10-12', 'users': {'123': {'name': 'Employé de test', 'count': 7}}},
    }}
    with app.state.store.connect(True) as db:
        db.execute('UPDATE domain_store SET body=? WHERE id=1', (json.dumps(fixture),))
        # Inclure le profil de test dans la liste Équipe pour vérifier son avatar.
        db.execute('UPDATE users SET member=1 WHERE id=?', ('local-preview',))
        db.execute('INSERT INTO roles(id,name,position,active) VALUES(?,?,?,1)', ('100', 'Rôle de test', 1))
        db.execute('INSERT INTO access_roles VALUES(?)', ('100',))
        db.execute('INSERT INTO role_permissions VALUES(?,?,1)', ('100', 'overview'))
        for _ in range(70):
            app.state.store.audit(db, 'local-preview', 'page_view', {'page': 'overview', 'actorName': 'Aperçu local'})
    return app, cfg


def run(args):
    import uvicorn

    chrome = Path(args.chrome_binary).resolve()
    driver_binary = Path(args.driver_binary).resolve()
    for binary in (chrome, driver_binary):
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise ValueError('Binaire exécutable introuvable : ' + str(binary))
    output = Path(args.output_dir).resolve() if args.output_dir else None
    if output:
        output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='heritage-chromium-test-') as temporary:
        root = Path(temporary)
        app, cfg = build_fixture(root)
        requests, bootstrap_payloads = [], []

        @app.middleware('http')
        async def observe(request, call_next):
            requests.append({'method': request.method, 'path': request.url.path, 'query': str(request.url.query)})
            response = await call_next(request)
            if request.url.path == '/api/bootstrap' and response.status_code == 200:
                from fastapi.responses import JSONResponse
                body = b''.join([part async for part in response.body_iterator])
                data = json.loads(body)
                bootstrap_payloads.append(data)
                return JSONResponse(data, headers={key: value for key, value in response.headers.items()
                                                   if key.lower() != 'content-length'})
            return response

        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=0,
                                               access_log=False, log_level='critical'))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        driver_process = None
        driver = None
        try:
            until = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < until:
                time.sleep(.05)
            assert server.started, 'Le serveur temporaire ne démarre pas.'
            origin = 'http://127.0.0.1:' + str(server.servers[0].sockets[0].getsockname()[1])
            cfg.base_url = origin
            driver_port = free_port()
            driver_log = root / 'chromedriver.log'
            process_log = root / 'chromedriver-process.log'
            chrome_log = root / 'chrome.log'
            with process_log.open('w') as log:
                driver_process = subprocess.Popen([str(driver_binary), '--port=' + str(driver_port),
                                                     '--allowed-ips=127.0.0.1', '--verbose',
                                                     '--log-path='+str(driver_log)], stdout=log, stderr=log,
                                                   env={**os.environ,'CHROME_LOG_FILE':str(chrome_log)},
                                                   start_new_session=True)
            driver_origin = 'http://127.0.0.1:' + str(driver_port)
            until = time.monotonic() + 10
            with httpx.Client(timeout=1, trust_env=False) as client:
                while time.monotonic() < until:
                    try:
                        if client.get(driver_origin + '/status').json()['value']['ready']:
                            break
                    except (httpx.HTTPError, ValueError, KeyError):
                        pass
                    if driver_process.poll() is not None:
                        raise RuntimeError('ChromeDriver ne démarre pas : ' + process_log.read_text()[-500:])
                    time.sleep(.05)
                else:
                    raise RuntimeError('ChromeDriver ne répond pas.')
            driver = WebDriver(driver_origin)
            capabilities = driver.start(chrome, root / 'chrome-profile', args.no_sandbox,
                                        startup_timeout=args.startup_timeout, debug_transport=args.debug_transport)
            driver.cdp('Page.addScriptToEvaluateOnNewDocument', source="""
window.__chromiumAuditErrors=[];
window.addEventListener('error',event=>{if(event.target===window||event.error)window.__chromiumAuditErrors.push({kind:'error',message:String(event.message).slice(0,300)});},true);
window.addEventListener('unhandledrejection',event=>window.__chromiumAuditErrors.push({kind:'promise',message:String(event.reason).slice(0,300)}));
""")
            driver.cdp('Network.enable')
            driver.cdp('Network.setBlockedURLs', urls=['https://fonts.googleapis.com/*', 'https://fonts.gstatic.com/*',
                                                       'https://discord.com/*', 'https://cdn.discordapp.com/*',
                                                       'https://media.discordapp.net/*'])
            driver.command('POST', '/window/rect', {'width': 1440, 'height': 1000})
            started = time.monotonic()
            driver.command('POST', '/url', {'url': origin + '/'})
            driver.wait("return !!document.querySelector('.night-metrics') && document.querySelector('#content').getAttribute('aria-busy')==='false' && document.querySelector('#initial-loading').hidden;")
            initial_ms = round((time.monotonic() - started) * 1000, 1)
            assert len(bootstrap_payloads) == 1, 'Un seul préchargement initial est attendu.'
            assert set(bootstrap_payloads[0]['pages']) == set(ROUTES)
            assert not any(item['path'].startswith('/api/pages/') for item in requests)

            def screenshot(name):
                if output:
                    encoded = driver.command('GET', '/screenshot')
                    (output / (name + '.png')).write_bytes(base64.b64decode(encoded))

            def navigate(page):
                driver.script("""
const [page,selector]=arguments,content=document.querySelector('#content');
window.__chromiumProbe={start:performance.now(),done:null,sawSpinner:false};
window.__chromiumObserver?.disconnect();
window.__chromiumObserver=new MutationObserver(()=>{
 if(content.querySelector('.loading-state,.loading-spinner,.loading-skeleton')||content.classList.contains('is-refreshing'))window.__chromiumProbe.sawSpinner=true;
 if(location.hash==='#'+page&&content.querySelector(selector)&&content.getAttribute('aria-busy')!=='true'&&document.querySelector('#navigation .active')?.dataset.page===page){window.__chromiumProbe.done=performance.now()-window.__chromiumProbe.start;window.__chromiumObserver.disconnect();}
});window.__chromiumObserver.observe(document.body,{childList:true,subtree:true,attributes:true,characterData:true});
if(location.hash==='#'+page)void window.heritageNavigate();else location.hash=page;
""", page, ROUTES[page])
                probe = driver.wait('return window.__chromiumProbe.done!==null && window.__chromiumProbe;')
                assert not probe['sawSpinner'], (page, probe)
                assert driver.script("return document.querySelector('#site-error').hidden;"), page
                return round(probe['done'], 2)

            before_navigation = len(requests)
            desktop = {page: navigate(page) for page in [*list(ROUTES)[1:], 'overview']}
            data_reads = [item for item in requests[before_navigation:]
                          if item['method'] == 'GET' and (item['path'] == '/api/bootstrap'
                          or item['path'].startswith('/api/pages/') and item['path'].count('/') == 3)]
            assert not data_reads, data_reads
            fade = driver.script("""
const style=getComputedStyle(document.querySelector('#sidebar'),'::before');
return {mask:style.maskImage,webkitMask:style.getPropertyValue('-webkit-mask-image'),mode:style.maskMode,background:style.backgroundImage,height:style.height,supports:CSS.supports('mask-image','linear-gradient(transparent,black)')};
""")
            assert fade['supports'] and 'linear-gradient' in fade['mask']
            assert 'midnight-statue.png' in fade['background'] and fade['mode'] == 'alpha'
            screenshot('chromium-desktop-overview')
            driver.script("document.querySelector('#profile-toggle').click();")
            assert driver.script("return !document.querySelector('#profile-menu').hidden;")
            driver.script("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));")
            assert driver.script("return document.querySelector('#profile-menu').hidden;")
            navigate('tombola')
            driver.script("document.querySelector('#content [data-action=raffle-record]').click();")
            driver.wait("return document.querySelector('#form-dialog').open && document.querySelectorAll('.vehicle-fields').length>=2;")
            driver.script("document.querySelector('#form-fields [name=price0]').value='50000';document.querySelector('#form-fields').dispatchEvent(new Event('input',{bubbles:true}));")
            assert '50' in driver.script("return document.querySelector('#raffle-known-total').textContent;")
            screenshot('chromium-tombola-dialog')
            driver.script("document.querySelector('#close-dialog').click();")

            profile_checked = False
            if args.workflows:
                from PIL import Image
                image_path = root / 'fixture-avatar.png'
                Image.new('RGB', (32, 32), '#31546b').save(image_path)
                navigate('profile')
                element = driver.command('POST', '/element', {'using': 'css selector', 'value': '#secure-profile-form [name=photo]'})
                identifier = element['element-6066-11e4-a52e-4f735466cecf']
                driver.command('POST', '/element/' + identifier + '/value', {'text': str(image_path), 'value': [str(image_path)]})
                driver.script("document.querySelector('#secure-profile-form [name=displayName]').value='Profil Chromium vérifié';document.querySelector('#secure-profile-form').requestSubmit();")
                driver.wait("return document.querySelector('.register-heading h2')?.textContent==='Profil Chromium vérifié' && !document.querySelector('#secure-profile-form [type=submit]').disabled;")
                assert driver.script("return document.querySelector('.register-avatar').getAttribute('src').startsWith('/api/me/avatar?');")
                navigate('team')
                driver.wait("return document.querySelector('.team-grid').textContent.includes('Profil Chromium vérifié') && [...document.querySelectorAll('.team-grid img')].some(image=>image.complete&&image.naturalWidth>0);")
                profile_checked = True

            driver.cdp('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=1, mobile=True)
            driver.cdp('Emulation.setTouchEmulationEnabled', enabled=True)
            mobile = {}
            for page in ROUTES:
                duration = navigate(page)
                size = driver.script("return {viewport:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,inner:innerWidth};")
                assert size['viewport'] == 390, size
                assert size['scroll'] <= size['viewport'] + 1, (page, size)
                mobile[page] = {**size, 'navigation_ms': duration}
            navigate('overview')
            driver.script("document.querySelector('#menu-toggle').click();")
            assert driver.script("return document.querySelector('#sidebar').classList.contains('open') && document.querySelector('#menu-toggle').getAttribute('aria-expanded')==='true';")
            driver.wait("return document.querySelector('#sidebar').getBoundingClientRect().left>=-.5;")
            screenshot('chromium-mobile-sidebar')
            driver.script("document.querySelector('#scrim').click();")
            assert driver.script("return !document.querySelector('#sidebar').classList.contains('open');")
            screenshot('chromium-mobile-overview')
            browser_logs = driver.command('POST', '/log', {'type': 'browser'})
            javascript_logs = [entry for entry in browser_logs if entry.get('level') == 'SEVERE'
                               and entry.get('source') in ('javascript', 'console-api')]
            errors = driver.script('return window.__chromiumAuditErrors;')
            assert not errors and not javascript_logs, {'events': errors, 'logs': javascript_logs}
            result = {'ok': True, 'browser': capabilities.get('browserName'),
                      'version': capabilities.get('browserVersion'), 'isolated_fixture': True,
                      'initial_loading_ms': initial_ms, 'initial_preloaded_pages': len(ROUTES),
                      'cached_navigation_ms': desktop, 'cached_page_data_gets': len(data_reads),
                      'cached_navigation_spinners': False, 'sidebar_gradient_css': fade,
                      'profile_menu_and_tombola_modal': True, 'mobile_menu': True,
                      'profile_upload_and_team_avatar': profile_checked,
                      'mobile_390_without_overflow': mobile, 'javascript_errors': errors,
                      'javascript_console_errors': javascript_logs, 'javascript_error_count': len(errors) + len(javascript_logs),
                      'external_fonts_blocked_for_isolation': True}
            if output:
                (output / 'chromium-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
            return result
        finally:
            if driver:
                try:
                    driver.close()
                except Exception:
                    pass
            if driver_process:
                # Nettoyer seulement le groupe propre à CE test, même si le pilote
                # n'a pas renvoyé d'identifiant de session après un échec au démarrage.
                try:
                    os.killpg(driver_process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    driver_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(driver_process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    driver_process.wait()
            server.should_exit = True
            thread.join(timeout=10)
            if output:
                for name in ('chromedriver.log','chromedriver-process.log','chrome.log'):
                    if (root/name).exists():
                        (output/name).write_text((root/name).read_text(errors='replace'))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--chrome-binary', default=os.getenv('CHROME_BINARY'))
    parser.add_argument('--driver-binary', default=os.getenv('CHROMEDRIVER_BINARY'))
    parser.add_argument('--no-sandbox', action='store_true')
    parser.add_argument('--startup-timeout', type=float, default=75, help='Délai maximal de création de session WebDriver, en secondes (75 par défaut).')
    parser.add_argument('--debug-transport', choices=('port','pipe'), default='port', help='Transport DevTools utilisé par ChromeDriver (port ou pipe).')
    parser.add_argument('--workflows', action='store_true', help='Tester aussi un upload de photo et son affichage dans Équipe.')
    parser.add_argument('--output-dir', help='Conserver JSON, captures et journal du pilote dans ce dossier.')
    args = parser.parse_args()
    if not args.chrome_binary or not args.driver_binary:
        parser.error('Indique --chrome-binary et --driver-binary, ou CHROME_BINARY et CHROMEDRIVER_BINARY.')
    if not 1<=args.startup_timeout<=180:
        parser.error('--startup-timeout doit être compris entre 1 et 180 secondes.')
    try:
        result = run(args)
    except Exception as error:
        print(json.dumps({'ok': False, 'error': type(error).__name__, 'message': str(error)[:1000]}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
