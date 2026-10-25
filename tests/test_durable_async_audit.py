import asyncio
import json
import threading

import httpx
import pytest
from starlette.responses import JSONResponse

from backend.auditing import AuditHTTPMiddleware, DurableAuditWriter
from backend.storage import Store


def test_concurrent_http_logs_share_commit_and_keep_individual_request_ids(tmp_path, monkeypatch):
    store = Store(tmp_path/'audit.sqlite3')
    writer = DurableAuditWriter(store)
    batches = []
    original = writer._persist
    def persist(batch):
        batches.append(len(batch))
        original(batch)
    monkeypatch.setattr(writer, '_persist', persist)
    async def endpoint(scope, receive, send):
        scope.setdefault('state', {})['identity'] = {'id':'test-member'}
        await JSONResponse({'ok':True})(scope, receive, send)
    app = AuditHTTPMiddleware(endpoint, store, 'session', writer)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            responses = await asyncio.gather(*[client.get('/api/pages/machines',headers={'X-Heritage-Visit':'1'}) for _ in range(20)])
        await writer.close()
        return responses
    responses = asyncio.run(check())
    with store.connect() as db:
        rows = [dict(row) for row in db.execute('SELECT * FROM audit')]
    assert len(rows)==20 and sum(batches)==20 and len(batches)<20
    assert {json.loads(row['detail'])['requestId'] for row in rows}=={response.headers['X-Request-ID'] for response in responses}
    assert all(row['kind']=='page_view' and row['actor']=='test-member' for row in rows)
    assert all(json.loads(row['detail'])['route']=='/api/pages/machines' for row in rows)


def test_http_waits_for_durable_commit_without_blocking_the_event_loop(tmp_path, monkeypatch):
    store = Store(tmp_path/'audit.sqlite3')
    writer = DurableAuditWriter(store)
    entered, release = threading.Event(), threading.Event()
    thread_ids = []
    original = writer._persist
    def persist(batch):
        thread_ids.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        original(batch)
    monkeypatch.setattr(writer, '_persist', persist)
    sent = []
    async def endpoint(scope, receive, send):
        await JSONResponse({'ok':True})(scope, receive, send)
    app = AuditHTTPMiddleware(endpoint, store, 'session', writer)
    async def check():
        async def receive(): return {'type':'http.request','body':b''}
        async def send(message): sent.append(message)
        scope={'type':'http','path':'/api/pages/machines','method':'GET','headers':[],'state':{}}
        task = asyncio.create_task(app(scope,receive,send))
        try:
            assert await asyncio.to_thread(entered.wait,3)
            for _ in range(5): await asyncio.sleep(.005)
            assert not sent and not task.done()
            assert thread_ids[0]!=threading.get_ident()
        finally:
            release.set()
        await task
        assert sent[0]['type']=='http.response.start' and sent[0]['status']==200
        with store.connect() as db: assert db.execute('SELECT count(*) FROM audit').fetchone()[0]==1
        await writer.close()
    asyncio.run(check())


def test_cancelled_http_waiter_does_not_cancel_its_permanent_log(tmp_path, monkeypatch):
    store = Store(tmp_path/'audit.sqlite3')
    writer = DurableAuditWriter(store)
    entered, release = threading.Event(), threading.Event()
    original = writer._persist
    def persist(batch):
        entered.set()
        assert release.wait(5)
        original(batch)
    monkeypatch.setattr(writer, '_persist', persist)
    async def check():
        task = asyncio.create_task(writer.append('test-member','page_view',{'requestId':'cancelled-request'}))
        try:
            assert await asyncio.to_thread(entered.wait,3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        finally:
            release.set()
        await writer.close()
    asyncio.run(check())
    with store.connect() as db:
        assert json.loads(db.execute('SELECT detail FROM audit').fetchone()[0])['requestId']=='cancelled-request'


def test_failed_batch_rolls_back_all_rows_and_fails_all_waiters(tmp_path, monkeypatch):
    store = Store(tmp_path/'audit.sqlite3')
    writer = DurableAuditWriter(store)
    original = store.audit
    def fail(db, actor, kind, detail):
        original(db,actor,kind,detail)
        if detail['record']=='bad': raise OSError('test-storage-failure')
    monkeypatch.setattr(store, 'audit', fail)
    async def check():
        results = await asyncio.gather(writer.append(None,'page_view',{'record':'good'}),
                                       writer.append(None,'page_view',{'record':'bad'}),return_exceptions=True)
        assert all(isinstance(result,OSError) for result in results)
        await writer.close()
    asyncio.run(check())
    with store.connect() as db: assert db.execute('SELECT count(*) FROM audit').fetchone()[0]==0


def test_cancelled_waiter_in_full_queue_is_still_logged_before_shutdown(tmp_path, monkeypatch):
    store = Store(tmp_path/'audit.sqlite3')
    writer = DurableAuditWriter(store)
    entered, release = threading.Event(), threading.Event()
    original = writer._persist
    def persist(batch):
        entered.set()
        assert release.wait(5)
        original(batch)
    monkeypatch.setattr(writer, '_persist', persist)
    async def check():
        writer.queue = asyncio.Queue(maxsize=1)
        first = asyncio.create_task(writer.append(None,'page_view',{'record':'first'}))
        try:
            assert await asyncio.to_thread(entered.wait,3)
            second = asyncio.create_task(writer.append(None,'page_view',{'record':'second'}))
            while not writer.queue.full(): await asyncio.sleep(0)
            third = asyncio.create_task(writer.append(None,'page_view',{'record':'third-cancelled'}))
            # L'appel troisième a passé le contrôle de fermeture et attend sa place.
            await asyncio.sleep(.01)
            assert not third.done() and len(writer.submissions) == 1
            third.cancel()
            with pytest.raises(asyncio.CancelledError): await third
            closing = asyncio.create_task(writer.close())
            await asyncio.sleep(.01)
            assert not closing.done()
            with pytest.raises(RuntimeError, match='fermé'):
                await writer.append(None,'page_view',{'record':'too-late'})
        finally:
            release.set()
        await closing
        await asyncio.gather(first,second)
    asyncio.run(check())
    with store.connect() as db:
        records = [json.loads(row[0])['record'] for row in db.execute('SELECT detail FROM audit ORDER BY id')]
    assert records == ['first','second','third-cancelled']
