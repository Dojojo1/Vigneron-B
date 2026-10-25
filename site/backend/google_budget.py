"""Transport Google de l'export de test ; ne modifie pas celui du bot."""
from pathlib import Path
from requests import Session
from requests.adapters import HTTPAdapter
from google.auth.transport.requests import AuthorizedSession, Request
from .budget_counter import WindowCounters, LimitReached


class GoogleBudgetExceeded(Exception):
    def __init__(self, retry_after):
        self.retry_after = retry_after


def limited_google_session(credentials, database: Path, per_minute=30, per_day=500):
    counters = WindowCounters(database)

    class BudgetAdapter(HTTPAdapter):
        def send(self, request, **kwargs):
            try:
                counters.consume('server', [('google-minute', per_minute, 60), ('google-day', per_day, 86400)])
            except LimitReached as error:
                raise GoogleBudgetExceeded(error.retry_after) from None
            return super().send(request, **kwargs)

    # Pas de retries internes urllib3 invisibles au compteur.
    auth_session = Session()
    for scheme in ('https://', 'http://'):
        auth_session.mount(scheme, BudgetAdapter(max_retries=0))
    session = AuthorizedSession(credentials, auth_request=Request(auth_session), refresh_timeout=10)
    for scheme in ('https://', 'http://'):
        session.mount(scheme, BudgetAdapter(max_retries=0))
    return session
