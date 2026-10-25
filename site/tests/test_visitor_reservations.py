import asyncio
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
import sqlite3
import time
from types import SimpleNamespace

import pytest

from backend.budget_counter import LimitReached, WindowCounters
from backend.traffic import VisitorLimitMiddleware


def used(path, category='requests'):
    with sqlite3.connect(path) as db:
        return sum(row[0] for row in db.execute('SELECT used FROM counters WHERE category=?', (category,)))


def test_durable_blocks_avoid_a_write_for_each_visitor_request(tmp_path, monkeypatch):
    path = tmp_path / 'limits.sqlite3'
    counters = WindowCounters(path, clock=lambda: 10)
    connect = sqlite3.connect
    writes = []

    def observe(*args, **kwargs):
        db = connect(*args, **kwargs)
        db.set_trace_callback(lambda statement: writes.append(statement) if statement == 'COMMIT' else None)
        return db

    monkeypatch.setattr(sqlite3, 'connect', observe)
    for _ in range(24):
        counters.consume_reserved('visitor', [('requests', 180, 60)])
    assert len(writes) == 3
    assert used(path) == 24


def test_concurrent_threads_and_instances_never_exceed_shared_cap(tmp_path):
    path = tmp_path / 'limits.sqlite3'
    counters = [WindowCounters(path, clock=lambda: 10) for _ in range(2)]

    def consume(index):
        try:
            counters[index % 2].consume_reserved('visitor', [('requests', 61, 60)])
            return 1
        except LimitReached:
            return 0

    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(consume, range(240))) == 61
    assert used(path) == 61


def test_restart_and_eviction_discard_unused_tickets_conservatively(tmp_path):
    path = tmp_path / 'limits.sqlite3'
    now = [10]
    first = WindowCounters(path, clock=lambda: now[0], reservation_cache_size=1)
    first.consume_reserved('visitor', [('requests', 10, 60)])
    assert used(path) == 8
    # Un redémarrage ne rembourse pas les sept tickets encore détenus par le premier processus.
    restarted = WindowCounters(path, clock=lambda: now[0], reservation_cache_size=1)
    restarted.consume_reserved('visitor', [('requests', 10, 60)])
    restarted.consume_reserved('other-visitor', [('requests', 10, 60)])
    assert len(restarted._reservations) == 1
    with pytest.raises(LimitReached):
        restarted.consume_reserved('visitor', [('requests', 10, 60)])
    # Les tickets restés dans le premier processus sont toujours déjà comptés.
    for _ in range(7):
        first.consume_reserved('visitor', [('requests', 10, 60)])
    with pytest.raises(LimitReached):
        first.consume_reserved('visitor', [('requests', 10, 60)])
    now[0] = 61
    restarted.consume_reserved('visitor', [('requests', 10, 60)])
    assert all(entry['expires'] == 120 for entry in restarted._reservations.values())


def test_multi_rule_failure_never_partially_allocates_or_uses_local_tickets(tmp_path):
    path = tmp_path / 'limits.sqlite3'
    counters = WindowCounters(path, clock=lambda: 10)
    counters.consume_reserved('visitor', [('requests', 180, 60), ('writes', 1, 60)])
    before = used(path)
    remaining = next(entry['remaining'] for key, entry in counters._reservations.items() if key[0] == 'requests')
    with pytest.raises(LimitReached) as raised:
        counters.consume_reserved('visitor', [('requests', 180, 60), ('writes', 1, 60), ('auth', 10, 600)])
    assert raised.value.retry_after == 50
    assert used(path) == before
    assert used(path, 'auth') == 0
    assert next(entry['remaining'] for key, entry in counters._reservations.items() if key[0] == 'requests') == remaining
    # L'ordre inverse ne doit pas réserver une nouvelle règle avant de découvrir le refus.
    with pytest.raises(LimitReached):
        counters.consume_reserved('visitor', [('auth', 10, 600), ('writes', 1, 60)])
    assert used(path, 'auth') == 0


def test_windows_retry_after_and_new_lower_cap_are_respected(tmp_path):
    now = [123.2]
    path = tmp_path / 'limits.sqlite3'
    counters = WindowCounters(path, clock=lambda: now[0])
    counters.consume_reserved('visitor', [('requests', 180, 60)])
    # Changer la configuration ne réutilise aucun ticket de l'ancien plafond.
    with pytest.raises(LimitReached) as raised:
        counters.consume_reserved('visitor', [('requests', 1, 60)])
    assert raised.value.retry_after == 57
    now[0] = 181
    counters.consume_reserved('visitor', [('requests', 1, 60), ('auth', 1, 600)])
    with pytest.raises(LimitReached) as raised:
        counters.consume_reserved('visitor', [('requests', 1, 60), ('auth', 1, 600)])
    assert raised.value.retry_after == 419
    now[0] = 601
    counters.consume_reserved('visitor', [('requests', 1, 60), ('auth', 1, 600)])


def test_reservation_cache_stays_bounded_and_is_not_written_for_expired_windows(tmp_path):
    now = [1]
    counters = WindowCounters(tmp_path / 'limits.sqlite3', clock=lambda: now[0], reservation_cache_size=3)
    for index in range(20):
        counters.consume_reserved(str(index), [('requests', 180, 60)])
        assert len(counters._reservations) <= 3
    now[0] = 61
    counters.consume_reserved('fresh', [('requests', 180, 60)])
    assert len(counters._reservations) == 1
    assert all(entry['expires'] == 120 for entry in counters._reservations.values())


def test_exact_provider_counts_do_not_reserve_ahead(tmp_path):
    path = tmp_path / 'limits.sqlite3'
    counters = WindowCounters(path, clock=lambda: 1)
    counters.consume('server', [('discord', 2, 60), ('discord-day', 3, 86400)])
    assert used(path, 'discord') == 1
    assert used(path, 'discord-day') == 1
    WindowCounters(path, clock=lambda: 1).consume('server', [('discord', 2, 60), ('discord-day', 3, 86400)])
    assert used(path, 'discord') == 2
    with pytest.raises(LimitReached):
        counters.consume('server', [('discord', 2, 60), ('discord-day', 3, 86400)])
    assert used(path, 'discord-day') == 2


def test_inherited_process_cannot_reuse_parent_tickets(tmp_path):
    path = tmp_path / 'limits.sqlite3'
    counters = WindowCounters(path, clock=lambda: 1)
    rules = [('requests', 9, 60)]
    counters.consume_reserved('visitor', rules)
    context = get_context('fork')
    receive, send = context.Pipe(duplex=False)

    def child():
        accepted = 0
        for _ in range(2):
            try:
                counters.consume_reserved('visitor', rules)
                accepted += 1
            except LimitReached:
                pass
        send.send(accepted)
        send.close()

    process = context.Process(target=child)
    process.start()
    send.close()
    try:
        assert receive.poll(5)
        assert receive.recv() == 1
        process.join(5)
        assert process.exitcode == 0
        for _ in range(7):
            counters.consume_reserved('visitor', rules)
        with pytest.raises(LimitReached):
            counters.consume_reserved('visitor', rules)
        assert used(path) == 9
    finally:
        receive.close()
        if process.is_alive():
            process.terminate()
            process.join(5)


def test_disk_reservation_does_not_block_asgi_event_loop():
    class SlowCounter:
        def consume_reserved(self, subject, rules):
            time.sleep(.15)

    async def application(scope, receive, send):
        return None

    settings = SimpleNamespace(visitor_per_minute=180, visitor_writes_per_minute=30, visitor_auth_per_ten_minutes=10)
    middleware = VisitorLimitMiddleware(application, SimpleNamespace(settings=settings, counters=SlowCounter()))

    async def check():
        task = asyncio.create_task(middleware({'type': 'http', 'method': 'GET', 'path': '/', 'client': ('127.0.0.1', 1)}, None, None))
        await asyncio.sleep(.02)
        assert not task.done(), 'Le disque a bloqué toute la boucle ASGI'
        await task

    asyncio.run(check())
