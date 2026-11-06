from starlette.responses import JSONResponse

AVATAR_MAX_BYTES = 10 * 1024 * 1024


def request_body_limit(path, default=2 * 1024 * 1024):
    # Allow multipart headers in addition to the photo itself.
    return AVATAR_MAX_BYTES + 64 * 1024 if path == '/api/me/avatar' else default


class BodyLimitMiddleware:
    """Limite aussi les corps chunked, avant tout parsing JSON/multipart."""
    def __init__(self,app,maximum=2*1024*1024): self.app,self.maximum=app,maximum
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope['method'] not in ('POST','PUT','PATCH'):
            return await self.app(scope,receive,send)
        maximum=request_body_limit(scope.get('path'), self.maximum)
        # La mémoire doit dépendre des octets reçus, pas du nombre de fragments.
        # Une liste pouvait grossir sans limite avec des fragments vides ou minuscules.
        body=bytearray()
        while True:
            message=await receive()
            if message['type']=='http.disconnect': return
            chunk=message.get('body',b'')
            if len(body)+len(chunk)>maximum:
                return await JSONResponse({'detail':'Requête trop volumineuse.'},status_code=413)(scope,receive,send)
            body.extend(chunk)
            if not message.get('more_body',False): break
        replayed=False
        async def replay():
            nonlocal replayed
            if not replayed:
                replayed=True
                return {'type':'http.request','body':bytes(body),'more_body':False}
            return await receive()
        return await self.app(scope,replay,send)
