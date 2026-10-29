"""Optional Linux restart command. NOT executed while preparing the handoff.

Defaults to inspection. With --restart, only stop the current user's recognized
loopback uvicorn process from the supplied site root, then run its existing
scripts/serve.py in the foreground. No .env or database is read or changed here.
"""
import argparse
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import time


def listening():
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(('127.0.0.1', 8081)) == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--restart', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    python = root / '.venv/bin/python'
    launcher = root / 'scripts/serve.py'
    if not python.is_file() or not launcher.is_file():
        raise SystemExit('Expected the existing site venv and scripts/serve.py.')
    pid = None
    if listening():
        sockets = subprocess.check_output(['ss', '-H', '-ltnp', '( sport = :8081 )'], text=True)
        ids = set(re.findall(r'pid=(\d+)', sockets))
        if len(ids) != 1 or '127.0.0.1:8081' not in sockets:
            raise SystemExit('Unrecognized listener; no process stopped.')
        pid = int(ids.pop())
        proc = Path('/proc') / str(pid)
        if proc.stat().st_uid != os.getuid() or (proc / 'cwd').resolve() != root:
            raise SystemExit('Different owner or project; no process stopped.')
        argv = (proc / 'cmdline').read_bytes().split(b'\0')
        expected = [str(python).encode(), b'-m', b'uvicorn', b'backend.app:create_app']
        if argv[:4] != expected:
            raise SystemExit('Different application; no process stopped.')
        def option(name):
            key = name.encode()
            return argv[argv.index(key) + 1] if key in argv else None
        if option('--host') != b'127.0.0.1' or option('--port') != b'8081':
            raise SystemExit('Unexpected binding; no process stopped.')
    if not args.restart:
        print('Recognized existing site.' if pid else 'Site is stopped.')
        print('Inspection only. Add --restart to restart in the foreground.')
        return
    if pid:
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 15
        while listening() and time.monotonic() < deadline:
            time.sleep(0.2)
        if listening():
            raise SystemExit('Port did not close; no second server started.')
    os.chdir(root)
    os.execv(str(python), [str(python), str(launcher)])


if __name__ == '__main__':
    main()
