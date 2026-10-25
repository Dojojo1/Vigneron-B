import asyncio
import tracemalloc

from backend.limits import BodyLimitMiddleware


def test_body_fragmentation_does_not_add_memory_per_fragment():
    received = []
    async def endpoint(scope, receive, send):
        received.append(await receive())
    async def run():
        chunks = 60000
        async def receive():
            nonlocal chunks
            chunks -= 1
            return {'type': 'http.request', 'body': b'x', 'more_body': bool(chunks)}
        async def send(message):
            raise AssertionError('Le petit corps ne doit pas être refusé.')
        await BodyLimitMiddleware(endpoint, maximum=65536)({'type': 'http', 'method': 'POST'}, receive, send)
    tracemalloc.start()
    try:
        asyncio.run(run())
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert received == [{'type': 'http.request', 'body': b'x' * 60000, 'more_body': False}]
    assert peak < 512000, f'Les fragments occupent {peak} octets pour un corps de 60000 octets'


def test_chunked_body_is_refused_before_endpoint_after_limit():
    sent = []
    async def endpoint(scope, receive, send):
        raise AssertionError('Le corps trop grand ne doit pas atteindre la route.')
    async def run():
        messages = iter([{'type': 'http.request', 'body': b'ab', 'more_body': True},
                         {'type': 'http.request', 'body': b'cd', 'more_body': False}])
        async def receive(): return next(messages)
        async def send(message): sent.append(message)
        await BodyLimitMiddleware(endpoint, maximum=3)({'type': 'http', 'method': 'PATCH'}, receive, send)
    asyncio.run(run())
    assert sent[0]['status'] == 413
