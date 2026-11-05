"""Compress public text assets without changing private API cache rules."""
from starlette.middleware.gzip import GZipMiddleware


class PublicAssetCompression(GZipMiddleware):
    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] == 'http' and not path.startswith(('/api/', '/auth/', '/internal/')) and path.endswith(('.js', '.css', '.svg')):
            return await super().__call__(scope, receive, send)
        return await self.app(scope, receive, send)
