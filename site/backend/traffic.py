"""Compteurs partagés entre processus, sans cookies ni identifiants du navigateur."""
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from .budget_counter import WindowCounters, LimitReached


class APIBudgetExceeded(HTTPException):
    reason = 'api_budget_exhausted'

    def __init__(self, provider, retry_after):
        super().__init__(503, f'Le plafond des appels vers {provider} est atteint. Réessaie dans {retry_after} secondes.',
                         headers={'Retry-After': str(retry_after)})


class TrafficLimits:
    def __init__(self, settings):
        self.settings = settings
        self.counters = WindowCounters(settings.data_dir / 'traffic-limits.sqlite3')

    def outgoing(self, provider):
        if provider not in ('discord', 'google'):
            raise ValueError('Fournisseur inconnu')
        rules = [(provider + '-minute', getattr(self.settings, provider + '_per_minute'), 60),
                 (provider + '-day', getattr(self.settings, provider + '_per_day'), 86400)]
        try:
            self.counters.consume('server', rules)
        except LimitReached as error:
            raise APIBudgetExceeded(provider.capitalize(), error.retry_after) from None

    def synchronization(self):
        try:
            self.counters.consume('server', [('bot-sync-hour', self.settings.sync_per_hour, 3600)])
        except LimitReached as error:
            raise APIBudgetExceeded('la synchronisation du bot', error.retry_after) from None


class VisitorLimitMiddleware:
    def __init__(self, app, limits):
        self.app, self.limits = app, limits

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        cfg = self.limits.settings
        # Ne jamais utiliser X-Forwarded-For, User-Agent ou un cookie fourni par le visiteur.
        address = str((scope.get('client') or ('unknown', 0))[0])
        rules = [('visitor-minute', cfg.visitor_per_minute, 60)]
        # La navigation conserve son quota global, sans consommer les tickets
        # réservés aux opérations métier lorsqu'elle journalise un changement de page.
        if scope['method'] not in ('GET', 'HEAD', 'OPTIONS') and not scope['path'].startswith('/api/visits/'):
            rules.append(('visitor-writes-minute', cfg.visitor_writes_per_minute, 60))
        if scope['path'] in ('/auth/start', '/auth/callback', '/auth/access-code'):
            rules.append(('visitor-auth-ten-minutes', cfg.visitor_auth_per_ten_minutes, 600))
        try:
            # Les réservations SQLite peuvent attendre le disque ou un autre processus.
            # Elles ne doivent jamais bloquer la boucle qui sert les autres requêtes.
            await run_in_threadpool(self.limits.counters.consume_reserved, address, rules)
        except LimitReached as error:
            response = JSONResponse(
                {'detail': f'Trop de requêtes. Patiente {error.retry_after} secondes avant de réessayer.',
                 'reason': 'visitor_rate_limited', 'retryAfter': error.retry_after},
                status_code=429, headers={'Retry-After': str(error.retry_after), 'Cache-Control': 'no-store',
                                         'X-Content-Type-Options': 'nosniff'})
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)
